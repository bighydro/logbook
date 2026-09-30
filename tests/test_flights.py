"""flight/v1 (RFC 0013): the airports and airlines tables, the flight key, the designator and the
declaration grammar, and the merge of observations across producers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import flights
from logbook.flights import Airlines, Airports

# -- airports ----------------------------------------------------------------------------------------


def test_airports_table_is_built_in_and_knows_major_airports():
    airports = Airports.load()
    assert len(airports) > 500
    osl = airports.get("OSL")
    assert osl is not None and osl.icao == "ENGM" and osl.tz == "Europe/Oslo"
    assert airports.get("engm") is osl  # by ICAO, any case
    assert airports.get("XXX") is None


def test_airports_every_row_has_a_zone_the_database_knows_and_coordinates_on_earth():
    import zoneinfo

    for airport in Airports.load():
        zoneinfo.ZoneInfo(airport.tz)
        assert -90 <= airport.lat <= 90 and -180 <= airport.lon <= 180
        assert len(airport.iata) == 3 and len(airport.icao) == 4


def test_airports_nearest_within_radius_else_none():
    airports = Airports.load()
    near_gate = airports.nearest(60.197, 11.104)  # a few hundred metres from OSL's reference point
    assert near_gate is not None and near_gate.iata == "OSL"
    assert airports.nearest(59.913, 10.752) is None  # Oslo city centre, 45 km away
    assert airports.nearest(59.913, 10.752, within_km=60) is not None


def test_airports_override_file_adds_a_private_field_and_overrides_a_row(tmp_path: Path):
    p = tmp_path / "airports.csv"
    p.write_text(
        "iata,icao,name,lat,lon,tz\n"
        "ZZZ,ENZZ,Example strip,60.5,11.5,Europe/Oslo\n"
        "OSL,ENGM,Oslo moved,61.0,12.0,Europe/Oslo\n",
        encoding="utf-8",
    )
    airports = Airports.load(p)
    assert airports.get("ZZZ") is not None and airports.get("ENZZ").name == "Example strip"
    assert airports.get("OSL").lat == 61.0
    assert airports.nearest(60.5, 11.5).iata == "ZZZ"


def test_airports_override_file_may_omit_icao_and_name(tmp_path: Path):
    p = tmp_path / "airports.csv"
    p.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Europe/Oslo\n", encoding="utf-8")
    z = Airports.load(p).get("ZZZ")
    assert z is not None and z.icao == "" and z.name == ""


def test_airports_override_file_with_a_bad_zone_or_no_code_is_refused(tmp_path: Path):
    p = tmp_path / "airports.csv"
    p.write_text("iata,lat,lon,tz\nZZZ,60.5,11.5,Mars/Olympus\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Mars/Olympus"):
        Airports.load(p)
    p.write_text("iata,lat,lon,tz\n,60.5,11.5,Europe/Oslo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        Airports.load(p)


# -- airlines -----------------------------------------------------------------------------------------


def test_airlines_spell_a_carrier_as_its_iata_designator():
    airlines = Airlines.load()
    assert airlines.iata("SWR") == "LX"  # Flighty exports ICAO
    assert airlines.iata("lx") == "LX"
    assert airlines.iata("XY") == "XY"  # unknown: as given, upper-case
    assert airlines.icao("LX") == "SWR" and airlines.icao("XY") is None
    assert airlines.knows("DLH") and airlines.knows("LH") and not airlines.knows("XY")


# -- the designator in a calendar title ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("LX 561", ("LX", "561")),
        ("LX561", ("LX", "561")),
        ("LX 0561", ("LX", "561")),
        ("Flight to Zurich (LX 561)", ("LX", "561")),
        ("SWR 561 to ZRH", ("LX", "561")),
        ("Flight XY 561 OSL-ZRH", ("XY", "561")),  # an unknown airline needs the word "flight"
        ("✈ XY 561", ("XY", "561")),
        ("XY 561", None),
        ("Q3 review", None),
        ("Room 12", None),
        ("Dinner at 8", None),
        ("", None),
    ],
)
def test_designator_in_a_title(title: str, expected: tuple[str, str] | None):
    assert flights.designator(title, Airlines.load()) == expected


def test_airport_codes_in_a_title_are_those_the_table_knows():
    airports = Airports.load()
    assert flights.route_in("Flight XY 561 OSL-ZRH", airports) == ("OSL", "ZRH")
    assert flights.route_in("XY 561 OSL → ZRH", airports) == ("OSL", "ZRH")
    assert flights.route_in("Flight to Zurich (LX 561)", airports) is None
    assert flights.route_in("BAD ONE", airports) is None


# -- the declaration --------------------------------------------------------------------------------


def test_declaration_minimal():
    d = flights.parse_declaration("XY 561 OSL ZRH 2026-09-27", Airports.load(), Airlines.load())
    p = d["payload"]
    assert d["source"] == "manual" and d["kind"] == "flight" and d["tier"] == 1
    assert (p["date"], p["carrier"], p["number"]) == ("2026-09-27", "XY", "561")
    assert p["from"] == {"iata": "OSL", "icao": "ENGM"} and p["to"] == {"iata": "ZRH", "icao": "LSZH"}
    assert p["role"] == "passenger" and p["evidence"] == "declared"
    assert p["observations"] == [{"evidence": "declared", "source": "manual"}]
    assert d["tz"] == "Europe/Oslo"
    assert d["at"] == "2026-09-26T22:00:00Z" and d["end"] is None  # no clock: local midnight at the origin
    assert "actual_departure" not in p


def test_declaration_full():
    d = flights.parse_declaration(
        "LX561 nce zrh 2026-09-27 pilot 07:05-08:20 A320 HB-JLT", Airports.load(), Airlines.load()
    )
    p = d["payload"]
    assert p["carrier"] == "LX" and p["carrier_icao"] == "SWR" and p["number"] == "561"
    assert p["role"] == "pilot"
    assert p["actual_departure"] == "2026-09-27T05:05:00Z"  # Nice, CEST
    assert p["actual_arrival"] == "2026-09-27T06:20:00Z"
    assert p["aircraft"] == {"type": "A320", "registration": "HB-JLT"}
    assert d["at"] == p["actual_departure"] and d["end"] == p["actual_arrival"]
    assert d["tz"] == "Europe/Paris"


def test_declaration_arrival_before_departure_is_the_next_day():
    d = flights.parse_declaration("XY 9 OSL JFK 2026-09-27 23:30-02:10", Airports.load(), Airlines.load())
    p = d["payload"]
    assert p["actual_departure"] == "2026-09-27T21:30:00Z"
    assert p["actual_arrival"] == "2026-09-28T06:10:00Z"  # 02:10 New York, the next local day


def test_declaration_unknown_airport_is_kept_without_a_zone():
    d = flights.parse_declaration("XY 561 ZZZ ZRH 2026-09-27 07:05-08:20", Airports.load(), Airlines.load())
    p = d["payload"]
    assert p["from"] == {"iata": "ZZZ"}
    assert "actual_departure" not in p and p["extra"]["departure_local"] == "2026-09-27T07:05"
    assert p["actual_arrival"] == "2026-09-27T06:20:00Z"
    assert d["tz"] is None and d["at"] == "2026-09-27T00:00:00Z"


@pytest.mark.parametrize(
    "text",
    [
        "XY 561 OSL ZRH",  # no date
        "XY 561 OSL ZRH 27-09-2026",
        "XY 561 OSL 2026-09-27",  # one airport
        "XY 561 OSL ZRH 2026-09-27 25:00-08:20",
        "561 OSL ZRH 2026-09-27",
    ],
)
def test_declaration_that_does_not_parse_says_why(text: str):
    with pytest.raises(ValueError):
        flights.parse_declaration(text, Airports.load(), Airlines.load())


def test_declaration_raw_id_is_the_key_with_a_digest_of_what_was_declared():
    a = flights.parse_declaration("XY 561 OSL ZRH 2026-09-27", Airports.load(), Airlines.load())
    b = flights.parse_declaration("XY 561 OSL ZRH 2026-09-27", Airports.load(), Airlines.load())
    c = flights.parse_declaration("XY 561 OSL ZRH 2026-09-27 pilot", Airports.load(), Airlines.load())
    assert a["payload"]["raw_id"] == b["payload"]["raw_id"] != c["payload"]["raw_id"]
    assert a["payload"]["raw_id"].startswith("2026-09-27:XY:561@")


# -- the key and the merge ----------------------------------------------------------------------------


def _line(seq: int, draft: dict, id_: str | None = None) -> dict:
    return {**draft, "id": id_ or f"id-{seq}", "seq": seq}


def _declared(**over):
    return flights.parse_declaration(
        over.pop("text", "XY 561 OSL ZRH 2026-09-27 pilot"), Airports.load(), Airlines.load()
    )


def _tracked(**fields):
    given = {
        "source": "flighty",
        "raw_id": "fx-1@abc",
        "airports": Airports.load(),
        "date": "2026-09-27",
        "carrier": "XY",
        "number": "561",
        "from_": {"iata": "OSL", "icao": "ENGM"},
        "to": {"iata": "ZRH", "icao": "LSZH"},
        "times": {
            "scheduled_departure": "2026-09-27T05:05:00Z",
            "actual_departure": "2026-09-27T05:10:00Z",
            "scheduled_arrival": "2026-09-27T06:20:00Z",
            "actual_arrival": "2026-09-27T06:24:00Z",
        },
        "aircraft": {"type": "Airbus A320", "registration": "LN-XYA"},
    }
    for field in flights.TIMES:
        if field in fields:
            given["times"][field] = fields.pop(field)
    given.update(fields)
    return flights.build(**given)


def test_key_is_date_carrier_number():
    assert flights.key(_declared()["payload"]) == ("2026-09-27", "XY", "561")
    assert flights.key(_tracked()["payload"]) == flights.key(_declared()["payload"])


def test_build_sets_at_end_and_tz_from_the_times_and_the_origin():
    d = _tracked()
    assert d["at"] == "2026-09-27T05:10:00Z" and d["end"] == "2026-09-27T06:24:00Z"
    assert d["tz"] == "Europe/Oslo"
    p = d["payload"]
    assert p["evidence"] == "tracked" and p["role"] == "passenger"
    assert p["observations"] == [{"evidence": "tracked", "source": "flighty"}]
    only_scheduled = _tracked(actual_departure=None, actual_arrival=None)
    assert only_scheduled["at"] == "2026-09-27T05:05:00Z" and only_scheduled["end"] == "2026-09-27T06:20:00Z"


def test_merge_tracked_over_declared_keeps_the_declared_role():
    current = _line(1, _declared())
    merged = flights.merge(current, _tracked())
    p = merged["payload"]
    assert p["supersedes"] == "id-1"
    assert p["evidence"] == "tracked" and p["role"] == "pilot"
    assert p["aircraft"] == {"type": "Airbus A320", "registration": "LN-XYA"}
    assert p["actual_departure"] == "2026-09-27T05:10:00Z"
    assert p["observations"] == [
        {"evidence": "declared", "source": "manual", "line": "id-1"},
        {"evidence": "tracked", "source": "flighty"},
    ]
    assert merged["source"] == "flighty" and merged["payload"]["raw_id"] == "fx-1@abc"
    assert merged["at"] == "2026-09-27T05:10:00Z" and merged["end"] == "2026-09-27T06:24:00Z"


def test_merge_declared_after_tracked_takes_only_the_role():
    current = _line(1, _tracked())
    merged = flights.merge(current, _declared())
    p = merged["payload"]
    assert p["evidence"] == "tracked" and p["role"] == "pilot"
    assert p["actual_departure"] == "2026-09-27T05:10:00Z" and p["aircraft"]["registration"] == "LN-XYA"
    assert merged["source"] == "manual" and merged["at"] == "2026-09-27T05:10:00Z"
    assert p["observations"][-1] == {"evidence": "declared", "source": "manual"}
    assert p["observations"][0] == {"evidence": "tracked", "source": "flighty", "line": "id-1"}


def test_merge_declared_role_survives_a_later_tracked_observation():
    first = _line(1, _declared())
    second = _line(2, flights.merge(first, _tracked()))
    third = flights.merge(second, _tracked(raw_id="fx-1@def", aircraft={"type": "Airbus A321"}))
    assert third["payload"]["role"] == "pilot"
    assert third["payload"]["aircraft"] == {"type": "Airbus A321"}  # the newer tracked wins between equals
    assert [o.get("line") for o in third["payload"]["observations"]] == ["id-1", "id-2", None]


def test_merge_fills_a_field_the_winner_lacks_from_the_loser():
    current = _line(1, _declared(text="XY 561 OSL ZRH 2026-09-27 pilot 07:05-08:20 A320 LN-XYB"))
    merged = flights.merge(current, _tracked(aircraft=None, actual_arrival=None))
    p = merged["payload"]
    assert p["aircraft"] == {"type": "A320", "registration": "LN-XYB"}
    assert p["actual_departure"] == "2026-09-27T05:10:00Z"  # the tracker's, not the declared 07:05
    assert p["actual_arrival"] == "2026-09-27T06:20:00Z"  # the declared arrival fills the gap


def test_standing_is_the_last_flight_line_no_other_supersedes_and_not_retracted():
    a = _line(1, _declared())
    b = _line(2, flights.merge(a, _tracked()))
    other = _line(3, _declared(text="XY 562 ZRH OSL 2026-09-28"))
    retraction = {
        "id": "id-4",
        "seq": 4,
        "kind": "retraction",
        "payload": {"schema": "retraction/v1", "supersedes": "id-3"},
    }
    for line in (a, b, other):
        line["kind"] = "flight"
    standing = flights.standing([a, b, other, retraction])
    assert standing == {("2026-09-27", "XY", "561"): b}
