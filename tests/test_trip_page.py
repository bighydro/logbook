"""`logbook trip <id-or-date> [--html PATH] [--json]`: one trip read back — the route as stays with
nights, the days inside it one line each, the flights in and out, the people confirmed and
proposed, the nights aboard, the keepers per day, the health of the span, the spend; `--html` one
self-contained page with an inline SVG map of the route. The synthetic demo record's yacht week
and the Oslo persona, who does not exist. Nothing is written."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from persona import KARI, OLA, TZ, ZURICH, persona_record, photo, utc

from logbook import cli, demo, trip_page
from logbook.store import Logbook

ARROW = "\u2192"
EN_DASH = "\u2013"
YACHT_WEEK = "trip:2026-06-15:2026-06-20"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """Thirty days of the demo record (seed 7), generated once for the module; nothing in it is real."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


# -- the yacht week ---------------------------------------------------------------------------------------


def test_the_yacht_week_is_its_anchorages_days_crew_keepers_health_and_spend(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    head = lb.meta["head"]
    data = _json(capsys, "trip", YACHT_WEEK)
    assert (data["id"], data["start"], data["end"], data["until"], data["nights"]) == (
        YACHT_WEEK,
        "2026-06-15",
        "2026-06-20",
        "2026-06-21",
        6,
    )
    assert data["head"] == head and data["warnings"] == []
    assert data["asset"] == demo.BOAT
    assert data["nights_aboard"] == [{"asset": demo.BOAT, "name": demo.BOAT_NAME, "nights": 6}]

    # The route is the anchorages the boat lay at each night, consecutive nights at one folded.
    route = data["route"]
    assert [s["n"] for s in route] == [1, 2, 3, 4, 5]
    assert [s["nights"] for s in route] == [1, 1, 2, 1, 1], "two nights in the harbour"
    assert [(s["first"], s["last"]) for s in route][2] == ("2026-06-17", "2026-06-18")
    assert all(s["aboard"] == demo.BOAT and s["asset"] == demo.BOAT_NAME for s in route)
    assert round(route[0]["lat"], 2) == 59.85 and round(route[0]["lon"], 2) == 10.6, "the first bay"
    assert route[-1]["label"] == "Marina" and route[-1]["place"] == "Marina", "the last night at the berth"
    assert route[0]["label"].startswith("59.85"), "an unnamed anchorage reads as its coordinates"
    assert not any(s["in_transit"] for s in route)
    legs = data["legs"]
    assert [(leg["from"], leg["to"]) for leg in legs] == [(1, 2), (2, 3), (3, 4), (4, 5)]
    assert all(leg["km"] > 5 for leg in legs) and not any(leg["through_transit"] for leg in legs)

    # The days inside it, one line each, as `days` prints them: the leaving day to the return day.
    days = data["days"]
    assert [d["day"] for d in days] == [f"2026-06-{n}" for n in range(15, 22)]
    assert days[0]["night"]["where"] == f"aboard {demo.BOAT_NAME}" and not days[0]["night"]["home"]
    assert days[-1]["night"]["home"], "the return day's night is at home"
    assert all(d["health"] is not None for d in days)

    assert data["flights_in"] == [] and data["flights_out"] == [] and data["flights"] == []
    confirmed = {p["name"] for p in data["people"]["confirmed"]}
    assert {"Ola Nordmann", "Anders Vik"} <= confirmed
    assert not {p["name"] for p in data["people"]["proposed"]} & confirmed, "a proposal never repeats"
    assert all(p["status"] == "confirmed" and p["sources"] for p in data["people"]["confirmed"])

    keepers = data["keepers"]
    assert [k["day"] for k in keepers["days"]] == ["2026-06-16", "2026-06-19", "2026-06-21"]
    assert keepers["count"] == 3 and keepers["memory"] == 3 and keepers["art"] == 0
    assert all(k["count"] == 1 and k["photos"] for k in keepers["days"])

    health = data["health"]
    assert health["sleep"]["nights"] == 7 and health["steps"]["days"] == 7
    assert health["resting_hr"]["min"] <= health["resting_hr"]["mean"] <= health["resting_hr"]["max"]
    assert health["hrv"] is None, "no HRV line in the demo: never a zero"

    spend = data["spend"]
    [nok] = spend["by_currency"]
    assert nok["currency"] == "NOK" and nok["amount"] < 0 and nok["count"] == 1
    [kiosk] = spend["transactions"]
    assert (kiosk["date"], kiosk["merchant"], kiosk["currency"]) == ("2026-06-18", "Havnekiosken", "NOK")
    assert kiosk["line"]
    assert lb.meta["head"] == head, "a trip is read, never written"


def test_the_text_reads_the_same_trip(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    text = _run(capsys, "trip", YACHT_WEEK)
    lines = text.splitlines()
    assert lines[0].startswith(f"{YACHT_WEEK}  2026-06-15 {EN_DASH} 2026-06-20")
    assert f"6 nights aboard {demo.BOAT_NAME}" in lines[0] and "until 2026-06-21" in lines[0]
    assert "  route" in text
    assert re.search(r"^\s+1\s+2026-06-15\s+1 night\s+59\.85", text, re.M), "the first anchorage"
    assert re.search(r"^\s+3\s+2026-06-17 \u2013 2026-06-18\s+2 nights", text, re.M), "the harbour"
    assert re.search(r"^\s+5\s+2026-06-20\s+1 night\s+Marina", text, re.M)
    assert "  flights       none" in text
    assert "  with          " in text and "Ola Nordmann" in text and "Anders Vik" in text
    assert f"  aboard        6 nights aboard {demo.BOAT_NAME}" in text
    assert "  days" in text
    assert re.search(rf"^    2026-06-15  Mon  aboard {demo.BOAT_NAME} NO", text, re.M), "a days row"
    assert re.search(r"^    2026-06-21  Sun  Home", text, re.M), "the return day"
    assert re.search(r"^  keepers       3 \(3 memory, 0 art\)", text, re.M)
    assert re.search(r"^    2026-06-16  1 memory", text, re.M)
    assert re.search(r"^  health        sleep \d\.\d h \(7 nights\)", text, re.M)
    assert re.search(r"^  spend         \u2212119 NOK \(1 transaction\)", text, re.M)
    assert re.search(r"^    2026-06-18  Havnekiosken\s+\u2212119 NOK\s+groceries", text, re.M)


def test_a_day_inside_the_trip_or_its_return_day_names_the_same_trip(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    for day in ("2026-06-15", "2026-06-18", "2026-06-21"):
        assert _json(capsys, "trip", day)["id"] == YACHT_WEEK, day


def test_the_zurich_trip_has_its_flights_and_its_spend_in_francs(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "trip", "2026-06-09")
    assert data["id"] == "trip:2026-06-08:2026-06-10" and data["asset"] is None
    assert [f["number"] for f in data["flights_in"]] == ["561"]
    assert [f["number"] for f in data["flights_out"]] == ["562"]
    assert [f["date"] for f in data["flights_out"]] == ["2026-06-11"]
    [hotel] = data["route"]
    assert hotel["nights"] == 3 and hotel["label"] == "47.3769,8.5417 (Zurich)" and hotel["aboard"] is None
    assert data["legs"] == [], "one stay: no leg"
    [chf] = data["spend"]["by_currency"]
    assert (chf["currency"], chf["amount"], chf["count"]) == ("CHF", -94.5, 1)
    assert data["nights_aboard"] == []
    text = _run(capsys, "trip", "trip:2026-06-08:2026-06-10")
    assert f"in XY 561 OSL {ARROW} ZRH" in text and f"out XY 562 ZRH {ARROW} OSL" in text
    assert "\u221294.50 CHF (1 transaction)" in text
    assert "  aboard" not in text, "no night aboard: no row"


def test_a_day_at_home_a_wrong_id_and_nonsense_say_so(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "2026-06-02"])
    assert e.value.code == 2
    assert "no trip on 2026-06-02" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "trip:2026-06-15:2026-06-19"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "no trip trip:2026-06-15:2026-06-19" in err and YACHT_WEEK in err, "the trip on that day is named"
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "yacht"])
    assert e.value.code == 2
    assert "not a trip id (trip:YYYY-MM-DD:YYYY-MM-DD) or a day" in capsys.readouterr().err
    with pytest.raises(ValueError):
        trip_page.parse_ref("trip:2026-06-20:2026-06-15")


def test_trips_prints_the_ids_a_trip_page_takes(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    text = _run(capsys, "trips", "--year", "2026")
    assert YACHT_WEEK in text and "trip:2026-06-08:2026-06-10" in text
    row = next(line for line in text.splitlines() if YACHT_WEEK in line)
    assert row.rstrip().endswith(YACHT_WEEK), "the id is the row's last part"


# -- the page ---------------------------------------------------------------------------------------------


def test_html_is_one_self_contained_page_with_an_svg_map_one_path_per_leg(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "pages" / "week.html"
    assert _run(capsys, "trip", YACHT_WEEK, "--html", str(out)) == f"trip {YACHT_WEEK}: wrote {out}\n"
    page = out.read_bytes().decode("utf-8")
    assert page.startswith("<!doctype html>") and "<style>" in page
    assert "<script" not in page and "http://" not in page and "https://" not in page
    assert "src=" not in page and "<link" not in page and "@import" not in page
    assert page.count("<svg") == 1 and 'xmlns="http://' not in page
    data = _json(capsys, "trip", YACHT_WEEK)
    assert page.count('<path class="leg') == len(data["legs"]) == 4, "one path per leg"
    assert page.count('<circle class="stay"') == 4 and len(data["route"]) == 5, "one mark per point"
    assert ">1, 4</text>" in page, "the bay slept in on the way out and the way back is one mark"
    assert re.search(r'<path class="leg" d="M[\d. ]+ L[\d. ]+"', page), "equirectangular: straight lines"
    assert "<table" in page and "Marina" in page and demo.BOAT_NAME in page
    assert "Havnekiosken" in page and "2026-06-16" in page
    assert "@page" in page and "@media print" in page, "printable"
    for section in ("route", "days", "flights", "people", "aboard", "keepers", "health", "spend"):
        assert f'<section id="{section}">' in page, section
    assert page == trip_page.html(data)


def test_the_page_escapes_what_the_record_says_and_a_single_stay_still_draws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many([_transaction(utc("2026-06-16", "19:30"), "<b>Gasthaus</b>", -80, "CHF")])
    out = tmp_path / "zurich.html"
    _run(capsys, "trip", "2026-06-16", "--html", str(out))
    page = out.read_text(encoding="utf-8")
    assert "&lt;b&gt;Gasthaus&lt;/b&gt;" in page and "<b>Gasthaus</b>" not in page
    assert page.count('<circle class="stay"') == 1 and '<path class="leg' not in page
    assert "<svg" in page, "one stay is still a map"


# -- the people and the spend, on the persona -------------------------------------------------------------


def test_a_tagged_face_is_proposed_and_a_dinner_guest_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [
            photo(utc("2026-06-16", "20:30"), ZURICH, people=[KARI["face"]]),
            _transaction(utc("2026-06-15", "12:00"), "Tram", -4.4, "CHF"),
            _transaction(utc("2026-06-16", "19:30"), "Dinner", -120, "CHF"),
            _transaction(utc("2026-06-17", "09:00"), "Kiosk", -45, "NOK"),
            _transaction(utc("2026-06-19", "09:00"), "After the trip", -99, "NOK"),
        ]
    )
    data = _json(capsys, "trip", "2026-06-16")
    assert data["id"] == "trip:2026-06-15:2026-06-17"
    assert [p["name"] for p in data["people"]["confirmed"]] == ["Ola Nordmann"]
    [kari] = data["people"]["proposed"]
    assert (kari["name"], kari["status"], kari["sources"]) == ("Kari Nordmann", "proposed", ["photo"])
    assert OLA["email"] not in json.dumps(data["people"]), "names, never addresses"
    assert data["spend"]["by_currency"] == [
        {"currency": "CHF", "amount": -124.4, "count": 2},
        {"currency": "NOK", "amount": -45, "count": 1},
    ], "summed per currency, the day after the return day out"
    assert [t["merchant"] for t in data["spend"]["transactions"]] == ["Tram", "Dinner", "Kiosk"]
    text = _run(capsys, "trip", "2026-06-16")
    assert "  with          Ola Nordmann · proposed Kari Nordmann" in text
    assert "  spend         \u2212124.40 CHF (2 transactions) · \u221245 NOK (1 transaction)" in text


def test_a_trip_with_no_transactions_has_no_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "trip", "2026-06-13")
    assert data["id"] == "trip:2026-06-13:2026-06-13" and data["spend"] is None
    assert data["nights_aboard"] == [{"asset": "solvind", "name": "Solvind", "nights": 1}]
    text = _run(capsys, "trip", "2026-06-13")
    assert "spend" not in text and "  aboard        1 night aboard Solvind" in text
    page = trip_page.html(data)
    assert '<section id="spend">' not in page


def test_without_a_home_place_or_days_the_command_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch, places=None)
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "2026-06-16"])
    assert e.value.code == 2 and "no place of kind home" in capsys.readouterr().err
    empty = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "2026-06-16"])
    assert e.value.code == 2 and "the record has no days" in capsys.readouterr().err


def _transaction(at: str, merchant: str, amount: float, currency: str) -> dict[str, Any]:
    return {
        "at": at,
        "end": None,
        "tz": TZ,
        "source": "copilot",
        "kind": "transaction",
        "tier": 3,
        "payload": {
            "schema": "transaction/v1",
            "raw_id": f"txn:{at}:{merchant}",
            "amount": amount,
            "currency": currency,
            "merchant": merchant,
            "category": "restaurants",
            "provider": "copilot",
            "status": "posted",
        },
    }
