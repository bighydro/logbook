"""A stay aboard an asset is a container: when an asset's own track lies within the radius of the
owner's points for twenty minutes or longer, the owner's stay is `aboard <asset>`, the asset's
movement never fragments it, and the night names the asset with the asset's position. `derive
stays`, `day`, `days`, `trips` and `rollup places|nights` all read it so. The fixture is the yacht
REDUCE, which does not exist, motoring 40 km through a night with the persona aboard, and the
control case: the persona ashore at a cabin 3 km away while the boat moves without them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import (
    ANCHORAGE_A,
    ANCHORAGE_B,
    CABIN,
    FJORD,
    HOME,
    MARINA,
    OLA_ID,
    PASSAGE_DAY,
    PASSAGE_NEXT,
    REDUCE,
    REDUCE_NAME,
    TZ,
    dwell,
    passage_record,
    travel,
    utc,
)

from logbook import cli, stays
from logbook.flights import distance_km
from logbook.store import Logbook

FRI, SAT = PASSAGE_DAY, PASSAGE_NEXT


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


def _owner(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in data["segments"] if s["subject"] is None]


def _near(a: tuple[float, float], lat: float, lon: float, km: float = 0.2) -> bool:
    return distance_km(a[0], a[1], lat, lon) <= km


def test_the_fixture_is_what_it_says() -> None:
    assert 39.5 < distance_km(*ANCHORAGE_A, *ANCHORAGE_B) < 40.5, "40 km through the night"
    assert 2.9 < distance_km(*ANCHORAGE_A, *CABIN) < 3.1, "the control case is ashore, 3 km off"


# -- derive stays ------------------------------------------------------------------------------------------


def test_derive_stays_folds_the_run_aboard_into_one_stay_with_the_passage_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    data = _json(capsys, "derive", "stays", "--since", FRI, "--until", SAT)
    assert data["settings"]["aboard_min_s"] == 1200
    owner = _owner(data)
    assert [s["kind"] for s in owner] == ["stay", "move", "stay", "move", "stay"]
    home, _drive, aboard, _back, home_again = owner
    assert home["aboard"] is None and "inside" not in home and home_again["place"] == "Home"
    assert aboard["aboard"] == REDUCE and aboard["place"] is None
    assert (aboard["start"], aboard["end"]) == (utc(FRI, "16:30"), utc(SAT, "12:00"))
    # its centre is the anchorage it lay longest at, so the id names it
    assert aboard["id"].startswith("stay:owner:20260703T1430Z@59.34")
    inside = aboard["inside"]
    assert [(s["kind"], s["aboard"], s.get("mode")) for s in inside] == [
        ("stay", REDUCE, None),
        ("move", REDUCE, "boat"),
        ("stay", REDUCE, None),
    ]
    assert _near(ANCHORAGE_A, inside[0]["lat"], inside[0]["lon"])
    assert _near(ANCHORAGE_B, inside[2]["lat"], inside[2]["lon"])
    assert 39_000 < inside[1]["distance_m"] < 41_000  # the boat's movement is inside the stay
    assert (inside[1]["start"], inside[1]["end"]) == (utc(FRI, "22:30"), utc(SAT, "03:00"))
    assert aboard["points"] == sum(s["points"] for s in inside)
    assert aboard["attached"] == {"note": 1} and inside[0]["attached"] == {"note": 1}
    assert aboard["lines"] == {
        "first": inside[0]["lines"]["first"],
        "last": inside[2]["lines"]["last"],
        "points": aboard["points"],
    }
    boat = [s for s in data["segments"] if s["subject"] == REDUCE]
    assert [s["kind"] for s in boat] == ["stay", "move", "stay"]
    assert all(s["aboard"] is None and "inside" not in s for s in boat), "aboard is the owner's relation"
    assert 39_000 < boat[1]["distance_m"] < 41_000 and boat[1]["mode"] == "boat"


def test_the_night_under_way_is_aboard_the_asset_at_the_assets_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    data = _json(capsys, "derive", "stays", "--since", FRI, "--until", SAT)
    night, after = data["nights"]
    assert night["day"] == FRI and night["in_transit"] is False and night["home"] is False
    assert night["aboard"] == REDUCE and night["stay"]["aboard"] == REDUCE
    assert night["stay"]["start"] == utc(FRI, "16:30"), "the whole run aboard is the night's stay"
    assert night["inside"]["kind"] == "stay", "where she lay for the longest part of the night"
    assert _near(ANCHORAGE_B, night["position"]["lat"], night["position"]["lon"])
    assert after["day"] == SAT and after["home"] is True and after["aboard"] is None
    assert _near(HOME, after["position"]["lat"], after["position"]["lon"]), "every night has a position"
    text = _run(capsys, "derive", "stays", "--since", FRI, "--until", SAT)
    assert "aboard reduce" in text and "40.0 km" in text and "boat" in text
    assert "night          aboard reduce · 59.3400,10.5500" in text
    assert text.count("aboard reduce") >= 2, "the stay's row and the night's row"


# -- day and days ------------------------------------------------------------------------------------------


def test_the_day_is_one_stay_aboard_and_the_header_names_the_asset_with_its_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    data = _json(capsys, "day", FRI)
    assert [e["kind"] for e in data["timeline"]] == ["stay", "move", "aboard"]
    aboard = data["timeline"][2]
    assert aboard["asset"] == {"id": REDUCE, "name": REDUCE_NAME, "kind": "yacht"}
    assert aboard["where"] == f"aboard {REDUCE_NAME}"
    assert aboard["start"] == utc(FRI, "16:30")
    assert aboard["end"] >= utc(SAT, "08:00"), "the Day reads through the night's end"
    assert aboard["within_day"]["end"] == utc(SAT, "00:00"), "clipped to the day; the span is kept"
    # only the rows that touch the day: the second anchorage is Saturday's
    assert [(s["kind"], s["mode"]) for s in aboard["inside"]] == [("stay", None), ("move", "boat")]
    assert 39_000 < aboard["inside"][1]["distance_m"] < 41_000
    assert [n["text"] for n in aboard["attached"]["notes"]] == [
        "Anchored for the night with Ola Nordmann; off at 22:30."
    ]
    [ola] = aboard["with"]["confirmed"]
    assert ola["person"] == OLA_ID
    after = data["nights"]["after"]
    assert after["aboard"] == REDUCE and after["where"] == f"aboard {REDUCE_NAME}" and after["home"] is False
    assert _near(ANCHORAGE_B, after["position"]["lat"], after["position"]["lon"]), "the asset's position"
    assert data["country"] == {
        "code": "NO",
        "method": "airport",
        "by": data["country"]["by"],
        "from": "night",
    }
    text = _run(capsys, "day", FRI)
    assert f"night after   aboard {REDUCE_NAME} · 59.3400,10.5500 · away" in text
    assert f"{REDUCE_NAME} (yacht)" in text and "40.0 km" in text and "boat" in text
    assert "night before  Home · home" in text
    # Saturday: the run aboard opens the day and the night before was aboard.
    saturday = _json(capsys, "day", SAT)
    assert [e["kind"] for e in saturday["timeline"]] == ["aboard", "move", "stay"]
    opening = saturday["timeline"][0]
    assert opening["within_day"]["start"] == utc(SAT, "00:00") and opening["start"] == utc(FRI, "16:30")
    assert [(s["kind"], s["mode"]) for s in opening["inside"]] == [("move", "boat"), ("stay", None)]
    assert saturday["nights"]["before"]["aboard"] == REDUCE
    assert _near(
        ANCHORAGE_B,
        saturday["nights"]["before"]["position"]["lat"],
        saturday["nights"]["before"]["position"]["lon"],
    )


def test_days_names_the_night_aboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    out = _run(capsys, "days", "--from", FRI, "--to", SAT, "--json")
    friday, saturday = (json.loads(line) for line in out.splitlines() if line)
    assert friday["night"]["where"] == f"aboard {REDUCE_NAME}" and friday["night"]["aboard"] == REDUCE
    assert friday["moved_m"] > 60_000, "the drive out and the passage, which started on the Friday"
    assert friday["stays"]["count"] == 2, "home and the run aboard"
    assert saturday["night"]["where"] == "Home"
    text = _run(capsys, "days", "--from", FRI, "--to", SAT)
    assert f"aboard {REDUCE_NAME} NO" in text


# -- trips and rollups -------------------------------------------------------------------------------------


def test_trips_shows_aboard_as_a_route_element_and_counts_the_nights_aboard_per_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    data = _json(capsys, "trips", "--since", FRI, "--until", SAT)
    [trip] = data["trips"]
    assert (trip["start"], trip["end"], trip["nights"]) == (FRI, FRI, 1)
    assert trip["asset"] == REDUCE
    assert trip["route"] == [f"aboard {REDUCE_NAME}"]
    assert trip["nights_aboard"] == {REDUCE: 1}
    assert [p["id"] for p in trip["people"]] == [OLA_ID]
    text = _run(capsys, "trips", "--since", FRI, "--until", SAT)
    assert f"1 night aboard {REDUCE_NAME}" in text and f"route aboard {REDUCE_NAME}" in text


def test_rollup_places_has_an_aboard_section_and_nights_counts_the_night_aboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch)
    data = _json(capsys, "rollup", "places", "--since", FRI, "--until", SAT)
    [year] = data["years"]
    [reduce] = year["aboard"]
    assert (reduce["asset"], reduce["name"], reduce["kind"]) == (REDUCE, REDUCE_NAME, "yacht")
    assert reduce["stays"] == 1 and reduce["nights"] == 1, "one run aboard, whatever the boat did inside it"
    assert 19 < reduce["hours"] < 20 and (reduce["first"], reduce["last"]) == (FRI, SAT)
    [ola] = reduce["people"]
    assert ola["id"] == OLA_ID and ola["nights"] == 1
    anchorages = [u for u in year["unnamed"] if u["aboard"] == REDUCE]
    assert len(anchorages) == 2, "both anchorages are unnamed places of their own, each aboard"
    assert anchorages[0]["nights"] == 1, "the night counts where she lay"
    assert _near(ANCHORAGE_B, anchorages[0]["lat"], anchorages[0]["lon"])
    assert anchorages[1]["nights"] == 0 and _near(ANCHORAGE_A, anchorages[1]["lat"], anchorages[1]["lon"])
    text = _run(capsys, "rollup", "places", "--since", FRI, "--until", SAT)
    assert (
        "aboard, by hours" in text
        and f"{REDUCE_NAME} ({REDUCE}) (yacht)" in text
        and "1 night · 1 stay" in text
    )
    nights = _json(capsys, "rollup", "nights", "--since", FRI, "--until", SAT)
    assert nights["years"][0]["aboard"] == {REDUCE: 1}


# -- the control case ---------------------------------------------------------------------------------------


def test_ashore_three_km_away_the_night_is_at_the_cabin_and_the_boat_moves_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passage_record(tmp_path, monkeypatch, aboard=False)
    data = _json(capsys, "derive", "stays", "--since", FRI, "--until", SAT)
    owner = _owner(data)
    assert [s["kind"] for s in owner] == ["stay", "move", "stay", "move", "stay"]
    assert all(s["aboard"] is None and "inside" not in s for s in owner)
    cabin = owner[2]
    assert _near(CABIN, cabin["lat"], cabin["lon"]) and (cabin["start"], cabin["end"]) == (
        utc(FRI, "16:30"),
        utc(SAT, "12:00"),
    )
    night = data["nights"][0]
    assert night["aboard"] is None and night["stay"]["id"] == cabin["id"] and night["inside"] is None
    assert _near(CABIN, night["position"]["lat"], night["position"]["lon"])
    boat = [s for s in data["segments"] if s["subject"] == REDUCE]
    assert [(s["kind"], s.get("mode")) for s in boat] == [("stay", None), ("move", "boat"), ("stay", None)]
    assert 39_000 < boat[1]["distance_m"] < 41_000
    day = _json(capsys, "day", FRI)
    assert [e["kind"] for e in day["timeline"]] == ["stay", "move", "stay"]
    assert day["nights"]["after"]["aboard"] is None
    assert str(day["nights"]["after"]["where"]).startswith("59.7000,10.6034")
    assert "aboard" not in _run(capsys, "day", FRI)
    trips = _json(capsys, "trips", "--since", FRI, "--until", SAT)
    [trip] = trips["trips"]
    assert (
        trip["asset"] is None
        and trip["nights_aboard"] == {}
        and trip["route"][0].startswith("59.7000,10.6034")
    )
    places = _json(capsys, "rollup", "places", "--since", FRI, "--until", SAT)
    assert places["years"][0]["aboard"] == []
    assert "aboard" not in _run(capsys, "rollup", "places", "--since", FRI, "--until", SAT)


# -- the twenty minutes --------------------------------------------------------------------------------------


def _quay_morning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minutes_alongside: int, aboard_min_s: int | None = None
) -> Logbook:
    """The owner sits at the marina from 09:00 to 12:00. Solvind lies out on the fjord, comes
    alongside at 10:00 for `minutes_alongside`, and goes out again."""
    day = "2026-06-10"
    leaves = f"10:{minutes_alongside:02d}"
    back = f"10:{minutes_alongside + 10:02d}"
    boat = "solvind"
    drafts = (
        dwell(day, "09:00", "12:00", MARINA, every_min=5, noise_m=15)
        + dwell(day, "06:00", "09:50", FJORD, every_min=2, noise_m=5, subject=boat)
        + travel(day, "09:50", "10:00", FJORD, MARINA, steps=10, subject=boat)
        + dwell(day, "10:00", leaves, MARINA, every_min=1, noise_m=5, subject=boat)
        + travel(day, leaves, back, MARINA, FJORD, steps=10, subject=boat)
        + dwell(day, back, "12:00", FJORD, every_min=2, noise_m=5, subject=boat)
    )
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(drafts)
    (lb.root / "assets.json").write_text(
        json.dumps({"assets": [{"id": boat, "kind": "yacht", "name": "Solvind", "mmsi": "999000001"}]}),
        encoding="utf-8",
    )
    if aboard_min_s is not None:
        stays.write_default_settings(lb.root)
        path = stays.settings_path(lb.root)
        settings = json.loads(path.read_text(encoding="utf-8"))
        settings["aboard_min_s"] = aboard_min_s
        path.write_text(json.dumps(settings), encoding="utf-8")
    return lb


def test_an_asset_alongside_for_less_than_twenty_minutes_does_not_put_the_owner_aboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _quay_morning(tmp_path, monkeypatch, minutes_alongside=10)
    data = _json(capsys, "derive", "stays", "--day", "2026-06-10")
    [quay] = _owner(data)
    assert quay["kind"] == "stay" and quay["aboard"] is None and "inside" not in quay
    assert data["nights"][0]["aboard"] is None


def test_an_asset_alongside_for_twenty_minutes_or_longer_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _quay_morning(tmp_path, monkeypatch, minutes_alongside=25)
    data = _json(capsys, "derive", "stays", "--day", "2026-06-10")
    [quay] = _owner(data)
    assert quay["kind"] == "stay" and quay["aboard"] == "solvind"
    assert [s["kind"] for s in quay["inside"]] == ["stay"], "a lone stay aboard is a container too"
    assert quay["inside"][0]["id"].startswith("stay:owner:") and quay["id"] == quay["inside"][0]["id"]


def test_the_threshold_is_a_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _quay_morning(tmp_path, monkeypatch, minutes_alongside=25, aboard_min_s=3600)
    data = _json(capsys, "derive", "stays", "--day", "2026-06-10")
    assert data["settings"]["aboard_min_s"] == 3600
    [quay] = _owner(data)
    assert quay["aboard"] is None
