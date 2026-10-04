"""The passages adapter: a ship's deck log transcribed as CSV → declared trip/v1 sea legs of a
registered asset (RFC 0020, mode `passage`, `subject` set) and location/v1 lines for the asset at
departure and arrival (RFC 0001, ADR 0018), positioned from ECDIS route files (RTZ 1.0), the
record's places.json or the bundled port gazetteer. Everything here is synthetic: the yacht Nordlys
(MMSI 970123456, which is allocated to no vessel) and her six legs never happened; the two RTZ files
are invented in the real schema; `Cala Nordlys` is on no chart."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters, asset_status
from logbook.contrib.adapters import passages
from logbook.core import assets, places, reading, stays
from logbook.core.assets import Asset
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "passages"
CSV = FIXTURES / "nordlys.csv"
ROUTES = FIXTURES / "routes"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
YACHT = Asset(id="nordlys", kind="yacht", name="Nordlys", mmsi="970123456")
LEGS = 6
POSITIONS = 10  # rows 1 to 4 both ends, row 5 the departure (the arrival is on no chart), row 6 the departure
HEADER = "dep_local,dep_place,arr_local,arr_place,tz,note,check\n"


def _run(
    path: Path = CSV, routes: Path | None = ROUTES, **kw: Any
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    counts: dict[str, int] = {}
    report: list[str] = []
    drafts = list(
        passages.run(
            path,
            counts=counts,
            timezone="Europe/Oslo",
            assets=[YACHT],
            asset="nordlys",
            routes=routes,
            report=report,
            **kw,
        )
    )
    return drafts, counts, report


def _legs(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [d for d in drafts if d["kind"] == "trip"]


def _positions(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [d for d in drafts if d["kind"] == "location"]


# -- registration and sniffing ----------------------------------------------------------------------------


def test_passages_is_a_registered_file_adapter_that_recognises_a_deck_log_csv():
    assert adapters.named("passages") is passages
    assert passages.NAME == "passages"
    assert passages.sniff(CSV)


def test_sniff_declines_other_csv_files_and_folders(tmp_path):
    other = tmp_path / "other.csv"
    other.write_text("date,flight,from,to\n2026-01-01,LX 561,NCE,ZRH\n", encoding="utf-8")
    assert not passages.sniff(other)
    assert not passages.sniff(tmp_path)
    assert not passages.sniff(tmp_path / "missing.csv")


# -- name matching -----------------------------------------------------------------------------------------


def test_normalise_is_case_accent_and_punctuation_insensitive_and_drops_filler_words():
    assert passages.normalise("Pollença") == passages.normalise("POLLENCA")
    assert passages.normalise("Saint-Tropez") == ("tropez",)
    assert passages.normalise("Genoa Molo Vecchio") == ("genoa", "vecchio")
    assert passages.normalise("Porto Cervo") == ("cervo",)
    assert passages.normalise("La Marina") == ("la", "marina")  # all filler: keep every word
    assert passages.normalise("") == ()


def test_a_route_matches_a_leg_by_token_overlap_in_either_direction():
    routes = passages.read_routes(ROUTES)
    assert [r.name for r in routes] == ["CANNES TO GENOA", "LA SPEZIA - BONIFACIO"]
    found = passages.match_route("Cannes", "Genoa Molo Vecchio", routes)
    assert found is not None and found[0].name == "CANNES TO GENOA" and found[1] is False
    found = passages.match_route("La Spezia", "Bonifacio", routes)
    assert found is not None and found[0].name == "LA SPEZIA - BONIFACIO" and found[1] is False
    back = passages.match_route("BONIFACIO", "la spezia", routes)
    assert back is not None and back[0].name == "LA SPEZIA - BONIFACIO" and back[1] is True
    assert passages.match_route("Genoa Molo Vecchio", "Portofino", routes) is None
    assert passages.match_route("Cannes", "Bonifacio", routes) is None


def test_a_route_without_a_separator_matches_when_both_places_are_named(tmp_path):
    (tmp_path / "r.rtz").write_text(
        '<?xml version="1.0"?><route xmlns="http://www.cirm.org/RTZ/1/0" version="1.0">'
        '<routeInfo routeName="Antibes Calvi summer"/><waypoints>'
        '<waypoint id="1"><position lat="43.587" lon="7.128"/></waypoint>'
        '<waypoint id="2"><position lat="42.567" lon="8.760"/></waypoint>'
        "</waypoints></route>",
        encoding="utf-8",
    )
    routes = passages.read_routes(tmp_path)
    found = passages.match_route("Port Vauban, Antibes", "Calvi", routes)
    assert found is not None and found[1] is False
    back = passages.match_route("Calvi", "Antibes", routes)
    assert back is not None and back[1] is True


def test_read_routes_names_a_nameless_route_after_its_file_and_ignores_what_is_not_rtz(tmp_path):
    (tmp_path / "Nice to Calvi.rtz").write_text(
        '<?xml version="1.0"?><route xmlns="http://www.cirm.org/RTZ/1/0" version="1.0"><routeInfo/>'
        '<waypoints><waypoint id="1"><position lat="43.694" lon="7.284"/></waypoint>'
        '<waypoint id="2"><position lat="42.567" lon="8.760"/></waypoint></waypoints></route>',
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("not a route", encoding="utf-8")
    (tmp_path / "broken.rtz").write_text("<route><waypoints>", encoding="utf-8")
    routes = passages.read_routes(tmp_path)
    assert [r.name for r in routes] == ["Nice to Calvi"]
    assert len(routes[0].waypoints) == 2
    assert 165_000 < routes[0].length_m < 180_000


# -- the gazetteer -----------------------------------------------------------------------------------------


def test_the_gazetteer_is_a_real_table_of_ports_in_the_three_cruising_grounds():
    ports = passages.gazetteer()
    assert len(ports) >= 150
    names = [p.name for p in ports]
    assert len(set(names)) == len(names)
    for p in ports:
        assert -90 <= p.lat <= 90 and -180 <= p.lon <= 180
        assert len(p.country) == 2 and p.country.isupper()
    countries = {p.country for p in ports}
    assert {"FR", "IT", "ES", "US", "BS"} <= countries
    assert passages.resolve("Genoa Molo Vecchio", [], ports) is not None
    assert passages.resolve("GENOVA", [], ports) is not None  # an alias
    assert passages.resolve("Staniel Cay", [], ports) is not None
    assert passages.resolve("Cala Nordlys", [], ports) is None


def test_places_json_is_asked_before_the_gazetteer():
    named = [places.Place("Cala Nordlys", 41.0, 9.5, 250.0), places.Place("Portofino", 10.0, 10.0, 80.0)]
    ports = passages.gazetteer()
    cove = passages.resolve("Cala Nordlys", named, ports)
    assert cove is not None and (cove.lat, cove.lon, cove.accuracy_m, cove.origin) == (
        41.0,
        9.5,
        250.0,
        "places",
    )
    home = passages.resolve("Portofino", named, ports)
    assert home is not None and (home.lat, home.lon, home.origin) == (10.0, 10.0, "places")


# -- the mapping -------------------------------------------------------------------------------------------


def test_six_rows_make_six_legs_and_ten_positions_oldest_first():
    drafts, counts, report = _run()
    assert len(_legs(drafts)) == LEGS
    assert len(_positions(drafts)) == POSITIONS
    assert [d["at"] for d in drafts] == sorted(d["at"] for d in drafts)
    assert counts == {}
    assert report == [
        "6 legs: 2 matched to a route, 1 open (no arrival yet)",
        "places unresolved: Cala Nordlys",
    ]
    for d in drafts:
        assert d["source"] == "passages" and d["tier"] == 1
        assert d["payload"]["subject"] == "nordlys"


def test_a_leg_matched_to_a_route_takes_its_ends_and_its_waypoints():
    leg = _legs(_run()[0])[0]
    p = leg["payload"]
    assert (leg["at"], leg["end"], leg["tz"]) == (
        "2026-06-14T06:30:00Z",
        "2026-06-14T15:10:00Z",
        "Europe/Paris",
    )
    assert p["schema"] == "trip/v1"
    assert p["mode"] == "passage" and p["provider"] == "deck-log"
    assert p["subject"] == "nordlys" and p["evidence"] == "declared"
    assert p["name"] == "Cannes → Genoa Molo Vecchio"
    assert p["raw_id"] == "passages:nordlys:2026-06-14T08:30:cannes"
    assert p["from"] == {"name": "Cannes", "latitude": 43.548, "longitude": 7.015}
    assert p["to"] == {"name": "Genoa Molo Vecchio", "latitude": 44.4075, "longitude": 8.926}
    assert p["geometry"]["type"] == "LineString"
    assert p["geometry"]["coordinates"] == [[7.015, 43.548], [7.13, 43.53], [8.05, 43.83], [8.926, 44.4075]]
    assert p["distance_m"] == 185_578  # the four waypoints, great-circle
    assert p["extra"]["route"] == {"name": "CANNES TO GENOA", "file": "CANNES TO GENOA.rtz"}
    assert p["extra"]["positions"] == {"from": "route", "to": "route"}
    assert "check" not in p["extra"] and "note" not in p["extra"] and "open" not in p["extra"]
    assert "status" not in p


def test_a_leg_with_no_route_is_positioned_from_the_gazetteer_and_keeps_the_note():
    leg = _legs(_run()[0])[1]
    p = leg["payload"]
    assert (leg["at"], leg["end"], leg["tz"]) == (
        "2026-06-16T07:00:00Z",
        "2026-06-16T13:40:00Z",
        "Europe/Rome",
    )
    assert p["name"] == "Genoa Molo Vecchio → Portofino"
    assert p["extra"]["positions"] == {"from": "gazetteer", "to": "gazetteer"}
    assert 44.3 < p["from"]["latitude"] < 44.5 and 8.8 < p["from"]["longitude"] < 9.0
    assert 44.25 < p["to"]["latitude"] < 44.35 and 9.15 < p["to"]["longitude"] < 9.25
    assert p["extra"]["note"] == "anchored off the harbour"
    assert "geometry" not in p and "distance_m" not in p and "route" not in p["extra"]


def test_a_row_with_dates_but_no_clocks_spans_the_local_days_and_says_so():
    leg = _legs(_run()[0])[2]
    assert leg["at"] == "2026-06-17T22:00:00Z"  # local midnight in Rome, CEST
    assert leg["end"] == "2026-06-18T21:59:59Z"  # the end of the arrival day
    assert leg["payload"]["extra"]["approximate"] == ["dep", "arr"]
    assert leg["payload"]["raw_id"] == "passages:nordlys:2026-06-18:portofino"


def test_a_row_with_a_check_value_is_imported_and_carries_it():
    leg = _legs(_run()[0])[3]
    p = leg["payload"]
    assert p["extra"]["check"] == "engine hours read 1830, log says 1803"
    assert p["extra"]["note"] == "overnight passage"
    assert p["extra"]["route"]["name"] == "LA SPEZIA - BONIFACIO"
    assert (leg["at"], leg["end"]) == ("2026-06-20T05:15:00Z", "2026-06-21T04:50:00Z")
    assert len(p["geometry"]["coordinates"]) == 5


def test_an_unresolved_place_keeps_its_name_without_a_position_and_is_counted():
    drafts, _, report = _run()
    leg = _legs(drafts)[4]
    assert leg["payload"]["to"] == {"name": "Cala Nordlys"}
    assert leg["payload"]["extra"]["positions"] == {"from": "gazetteer", "to": None}
    assert leg["end"] == "2026-06-23T11:30:00Z"  # the arrival time is known, only the position is not
    assert report[-1] == "places unresolved: Cala Nordlys"
    arrivals = [d for d in _positions(drafts) if d["payload"]["raw_id"].endswith(":arr")]
    assert not any(d["payload"]["extra"]["place"] == "Cala Nordlys" for d in arrivals)


def test_a_row_with_an_empty_arrival_is_an_open_leg_with_a_departure_line():
    drafts, _, report = _run()
    leg = _legs(drafts)[5]
    p = leg["payload"]
    assert leg["at"] == "2026-06-26T06:00:00Z" and leg["end"] is None
    assert "to" not in p and p["name"] == "Porto Cervo → ?"
    assert p["extra"]["open"] is True
    assert "1 open (no arrival yet)" in report[0]
    departure = [d for d in _positions(drafts) if d["payload"]["raw_id"] == p["raw_id"] + ":dep"]
    assert len(departure) == 1 and departure[0]["at"] == leg["at"]


def test_the_positions_are_the_assets_own_location_lines():
    drafts = _run()[0]
    leg = _legs(drafts)[0]
    dep, arr = (
        d for d in _positions(drafts) if d["payload"]["raw_id"].startswith(leg["payload"]["raw_id"] + ":")
    )
    for line, end, name, when in (
        (dep, "dep", "Cannes", leg["at"]),
        (arr, "arr", "Genoa Molo Vecchio", leg["end"]),
    ):
        p = line["payload"]
        assert (line["at"], line["end"], line["tz"]) == (when, None, "Europe/Paris")
        assert p["schema"] == "location/v1" and p["subject"] == "nordlys"
        assert p["provider"] == "manual" and p["tracker"] == "deck-log"
        assert p["raw_id"] == f"{leg['payload']['raw_id']}:{end}"
        assert p["extra"] == {
            "evidence": "declared",
            "place": name,
            "leg": leg["payload"]["raw_id"],
            "position": "route",
        }
    assert (dep["payload"]["lat"], dep["payload"]["lon"], dep["payload"]["accuracy_m"]) == (
        43.548,
        7.015,
        100,
    )
    gaz = next(d for d in _positions(drafts) if d["payload"]["extra"]["place"] == "Portofino")
    assert gaz["payload"]["accuracy_m"] == 1000 and gaz["payload"]["extra"]["position"] == "gazetteer"


def test_a_missing_tz_means_the_records_zone_and_an_unknown_one_is_a_counted_skip(tmp_path):
    csv = tmp_path / "log.csv"
    csv.write_text(
        HEADER + "2026-07-01 10:00,Portofino,2026-07-01 12:00,Rapallo,,,\n"
        "2026-07-02 10:00,Rapallo,2026-07-02 12:00,Portofino,Mars/Olympus,,\n",
        encoding="utf-8",
    )
    drafts, counts, _ = _run(csv, None)
    assert len(_legs(drafts)) == 1 and _legs(drafts)[0]["tz"] == "Europe/Oslo"
    assert _legs(drafts)[0]["at"] == "2026-07-01T08:00:00Z"
    assert counts["skipped_unknown_timezone"] == 1


def test_a_row_without_a_departure_time_or_place_is_a_counted_skip(tmp_path):
    csv = tmp_path / "log.csv"
    csv.write_text(
        HEADER + ",Portofino,2026-07-01 12:00,Rapallo,Europe/Rome,,\n"
        "2026-07-02 10:00,,2026-07-02 12:00,Portofino,Europe/Rome,,\n"
        "yesterday,Rapallo,,,Europe/Rome,,\n",
        encoding="utf-8",
    )
    drafts, counts, _ = _run(csv, None)
    assert drafts == []
    assert counts == {"skipped_no_timestamp": 2, "skipped_no_place": 1}


def test_an_arrival_place_without_a_clock_keeps_the_place_and_writes_no_arrival_line(tmp_path):
    csv = tmp_path / "log.csv"
    csv.write_text(HEADER + "2026-07-01 10:00,Portofino,,Rapallo,Europe/Rome,,\n", encoding="utf-8")
    drafts, _, report = _run(csv, None)
    leg = _legs(drafts)[0]
    assert leg["end"] is None and leg["payload"]["to"]["name"] == "Rapallo"
    assert "open" not in leg["payload"]["extra"] and report == ["1 leg"]
    assert len(_positions(drafts)) == 1


def test_since_is_honoured_and_the_asset_must_be_registered_and_given():
    drafts, _, _ = _run(since="2026-06-20T00:00:00Z")
    assert len(_legs(drafts)) == 3
    with pytest.raises(ValueError, match="--asset"):
        list(passages.run(CSV, assets=[YACHT]))
    with pytest.raises(ValueError, match="not registered"):
        list(passages.run(CSV, assets=[YACHT], asset="solvind"))


def test_every_line_validates_against_the_envelope_schema(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    drafts = _run()[0]
    assert lb.append_many(iter(drafts)) == LEGS + POSITIONS
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


# -- the command -------------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assets.add(lb.root, YACHT)
    return lb


def test_add_passages_writes_the_legs_and_reports_them(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    out = capsys.readouterr().out
    assert f"added {LEGS + POSITIONS} lines from passages" in out
    assert "  6 legs: 2 matched to a route, 1 open (no arrival yet)" in out
    assert "places unresolved: Cala Nordlys" in out
    assert sum(1 for line in lb.lines() if line["kind"] == "trip") == LEGS


def test_add_passages_again_appends_nothing(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    capsys.readouterr()
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    assert "added 0 lines from passages" in capsys.readouterr().out
    assert lb.meta["seq"] == LEGS + POSITIONS


def test_add_dry_run_writes_nothing_and_says_what_it_would(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES), "--dry-run"])
    out = capsys.readouterr().out
    assert f"passages: {LEGS + POSITIONS} lines would be added, 0 already in the record" in out
    assert "places unresolved: Cala Nordlys" in out
    assert lb.meta["seq"] == 0 and not list(lb.lines())
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    capsys.readouterr()
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--dry-run"])
    assert (
        f"passages: 0 lines would be added, {LEGS + POSITIONS} already in the record"
        in capsys.readouterr().out
    )


def test_add_passages_without_routes_uses_the_gazetteer_alone(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys"])
    out = capsys.readouterr().out
    assert f"added {LEGS + POSITIONS} lines from passages" in out
    assert "matched to a route" not in out


def test_add_passages_refuses_an_unregistered_or_missing_asset(lb, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "passages", str(CSV), "--asset", "solvind"])
    assert e.value.code == 2
    assert "solvind" in capsys.readouterr().err and lb.meta["seq"] == 0
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "passages", str(CSV)])
    assert e.value.code == 2
    assert "--asset" in capsys.readouterr().err and lb.meta["seq"] == 0


def test_add_refuses_asset_and_routes_for_an_adapter_that_does_not_take_them(lb, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(
            [
                "add",
                "ais",
                str(ROOT / "tests" / "fixtures" / "ais" / "messages.jsonl"),
                "--routes",
                str(ROUTES),
            ]
        )
    assert e.value.code == 2
    assert "--routes is not an option of the ais adapter" in capsys.readouterr().err


# -- the readers -------------------------------------------------------------------------------------------


def test_assets_status_reads_the_declared_departure_as_the_last_fix(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    capsys.readouterr()
    found = asset_status.read(
        lb, [YACHT], passages.gazetteer_places(), datetime(2026, 6, 26, 8, 0, tzinfo=UTC)
    )
    fix = found[0].fix
    assert fix is not None and fix.at == "2026-06-26T06:00:00Z"
    assert fix.near is not None and fix.near[0] == "Porto Cervo"
    cli.main(["assets", "status"])
    out = capsys.readouterr().out
    assert "nordlys" in out and "2026-06-26 08:00" in out and "41.1370,9.5350" in out


def test_the_stays_engine_derives_the_assets_passages_from_the_declared_positions(lb, capsys):
    cli.main(["add", "passages", str(CSV), "--asset", "nordlys", "--routes", str(ROUTES)])
    capsys.readouterr()
    read = reading.read(lb, "2026-06-14", "2026-06-26")
    assert "nordlys" in read.derived.subjects
    own = [s for s in read.segments if s.subject == "nordlys"]
    # An arrival and the next departure make a stay at the port; the span between two stays is a
    # move by boat. A lone fix (the first departure, the one after the unpositioned arrival, the
    # open leg's) is too short for a stop in the engine's grammar and makes no move on its own.
    assert [s.kind for s in own] == ["stay", "move", "stay", "move", "stay", "move", "stay"]
    stays_at = [(round(s.lat or 0, 2), round(s.lon or 0, 2)) for s in own if s.kind == stays.STAY]
    assert stays_at == [
        (44.41, 8.93),
        (44.3, 9.21),
        (44.1, 9.83),
        (41.39, 9.16),
    ]  # Genoa, Portofino, La Spezia, Bonifacio
    passage = own[5]
    assert passage.start == datetime(2026, 6, 20, 5, 15, tzinfo=UTC) and passage.end == datetime(
        2026, 6, 21, 4, 50, tzinfo=UTC
    )
    assert (
        passage.mode == "boat" and passage.distance_m is not None and 300_000 < passage.distance_m < 315_000
    )
    assert not [s for s in read.segments if s.subject is None], "the owner's track is untouched"
