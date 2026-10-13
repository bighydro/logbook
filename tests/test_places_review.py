"""`logbook setup places review`: the observed places of the record (clusters of the owner's stays),
the names the record already holds for each, and the owner's say — accept, name, reject — on a
synthetic fortnight at sea (`places_record`): 2,000 tracker points in twelve clusters, three named by
a Google Timeline export, one by a photo, one by a calendar entry. Nothing is ever looked up, and
the network guard stays on."""

from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from places_record import (
    BOATHOUSE,
    CABIN,
    CLUBHOUSE,
    DAYS,
    HOURS_BY_DAY,
    LIGHTHOUSE,
    NIGHTS_AT,
    TRACKER_POINTS,
    WORKSHOP,
    S,
    record,
)

from logbook import cli
from logbook.commands import places as places_command
from logbook.contrib import places_review, serve
from logbook.core import places
from logbook.core.store import Logbook

BLANK = places_review.BLANK


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("places-review") / "lb"
    record(root)
    return root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _review(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["setup", "places", "review", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_review(capsys, *args, "--json"))
    return data


def _spot(lat: float, lon: float) -> int:
    """The spot of the fortnight a centre lies at (within 30 m, else the test fails)."""
    n = min(S, key=lambda i: places.distance_m(lat, lon, *S[i]))
    assert places.distance_m(lat, lon, *S[n]) < 30, (lat, lon, n)
    return n


def _places_json(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    return data


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


# -- the observed places ----------------------------------------------------------------------------------


def test_two_thousand_points_cluster_into_twelve_observed_places(lb: Logbook) -> None:
    assert sum(1 for line in lb.lines() if line["source"] == "dawarich") == TRACKER_POINTS
    found = places_review.observed(lb)
    assert len(found) == 12
    assert sorted(_spot(o.lat, o.lon) for o in found) == list(range(1, 13))
    assert all(o.place is None and o.aboard is None for o in found)


def test_each_observed_place_counts_its_visits_nights_hours_first_and_last(lb: Logbook) -> None:
    by_spot = {_spot(o.lat, o.lon): o for o in places_review.observed(lb)}
    for n, nights in NIGHTS_AT.items():
        assert by_spot[n].nights == nights and by_spot[n].visits == nights, n
    for n, hours in HOURS_BY_DAY.items():
        assert by_spot[n].nights == 0 and by_spot[n].hours == pytest.approx(hours), n
    assert [by_spot[n].visits for n in range(5, 13)] == [5, 5, 4, 5, 4, 3, 2, 1]
    cabin = by_spot[1]
    assert cabin.first == "2026-02-02T20:00:00Z", "the first night: 21:00 in Oslo"
    assert cabin.last == "2026-02-14T07:00:00Z", "the last morning: 08:00"
    assert cabin.hours == pytest.approx(91.5)
    assert by_spot[12].first == "2026-02-14T12:30:00Z" and by_spot[12].last == "2026-02-14T15:30:00Z"
    assert cabin.spread_m < 10, "six nights at one spot, 20 m of GPS scatter: the centres agree"


def test_the_queue_ranks_by_nights_then_hours(lb: Logbook) -> None:
    report = places_review.read(lb)
    assert [_spot(p.observed.lat, p.observed.lon) for p in report.proposals] == list(range(1, 13))
    assert [p.number for p in report.proposals] == list(range(1, 13))


def test_each_proposal_names_what_the_record_holds_and_says_who_said_it(lb: Logbook) -> None:
    report = places_review.read(lb)
    names = [p.name for p in report.proposals]
    assert names == [CABIN, WORKSHOP, None, BOATHOUSE, LIGHTHOUSE, CLUBHOUSE, *[None] * 6]
    cabin = {(n.source, n.origin, n.name, n.grade): n.count for n in report.proposals[0].observed.names}
    assert cabin == {
        ("google-takeout", "timeline", CABIN, "name"): 3,
        ("google-takeout", "timeline", "Home", "type"): 3,
        ("immich", "photo", "Nordsjøen", "city"): 1,
    }, "the Timeline's name beats its semantic type and the photo's city"
    [lighthouse] = report.proposals[4].observed.names
    assert (lighthouse.source, lighthouse.origin, lighthouse.name, lighthouse.count) == (
        "apple-photos",
        "photo",
        LIGHTHOUSE,
        2,
    )
    [clubhouse] = report.proposals[5].observed.names
    assert (clubhouse.source, clubhouse.origin, clubhouse.name) == ("ios-calendar", "calendar", CLUBHOUSE)
    assert report.proposals[6].observed.names == [], "a Teams meeting names no place"
    assert report.proposals[7].observed.names == [], "an all-day entry names no hour, so no stay"
    assert report.proposals[2].observed.names == []


def test_review_prints_one_line_per_proposal_and_a_blank_where_no_source_knows(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _review(capsys)
    lines = out.splitlines()
    assert lines[0].startswith("12 places observed · 0 named · 12 to review")
    rows = [line for line in lines if re.match(r"^\s+\d+\s{2}", line)]
    assert len(rows) == 12
    assert rows[0].strip().startswith("1  55.6000,4.4000") and rows[0].endswith(f"→ {CABIN}")
    assert f"6 visits · 6 nights · 91.5 h · 2026-02-02 {places_review.EN_DASH} 2026-02-14" in rows[0]
    assert rows[2].endswith(f"→ {BLANK}")
    assert f'google-takeout timeline: "{CABIN}" (3 visits)' in out
    assert 'google-takeout timeline: "Home" (3 visits, type)' in out
    assert f'apple-photos: "{LIGHTHOUSE}" (2 photos)' in out
    assert f'ios-calendar: "{CLUBHOUSE}" (1 event)' in out
    assert "no source names it" in out
    assert lines[-1].startswith("nothing written")
    assert not (lb.root / "places.json").exists(), "never accepted on its own"
    assert not (lb.root / "state" / "places-review.json").exists()


def test_the_json_has_the_proposals_with_their_evidence_and_the_radius_they_would_get(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    assert (data["observed"], data["named"], data["radius_m"]) == (12, 0, 75)
    first = data["proposals"][0]
    assert first["number"] == 1 and first["name"] == CABIN
    assert (first["visits"], first["nights"], first["hours"]) == (6, 6, 91.5)
    assert first["first"] == "2026-02-02T20:00:00Z" and first["id"].startswith("place:55.6000,4.4000")
    assert first["radius_m"] == 80, "the spread (under 5 m) and 75 m of a stay's own scatter, up to 5 m"
    assert {"source": "google-takeout", "origin": "timeline", "name": CABIN, "grade": "name"}.items() <= (
        first["evidence"][0].items()
    )
    assert len(first["evidence"][0]["lines"]) == 3
    assert data["proposals"][2]["name"] is None and data["proposals"][2]["evidence"] == []


# -- the owner's say --------------------------------------------------------------------------------------


def test_accept_writes_the_place_at_the_cluster_s_centre_with_a_fitted_radius(
    lb: Logbook, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    before = _seq(lb)
    out = _review(capsys, "--accept", "1,2")
    assert f"accepted 1 → {CABIN}" in out and f"accepted 2 → {WORKSHOP}" in out
    written = _places_json(lb)
    assert set(written) == {CABIN, WORKSHOP}
    cabin = written[CABIN]
    assert places.distance_m(cabin["lat"], cabin["lon"], *S[1]) < 10
    assert cabin["radius_m"] == 80 and cabin["kind"] == "other"
    assert _seq(lb) == before + 2, "one naming note each, as `places name` writes"
    notes = [line for line in Logbook(lb.root).lines() if line["kind"] == "note"]
    assert [n["payload"]["text"].split(" as ")[1] for n in notes] == [CABIN, WORKSHOP]
    assert notes[0]["payload"]["text"].startswith("named 55.6")
    after = places_review.read(Logbook(lb.root))
    assert (len(after.observed), after.named, len(after.proposals)) == (12, 2, 10)
    assert after.proposals[0].number == 1 and _spot(after.proposals[0].lat, after.proposals[0].lon) == 3
    assert no_network == []


def test_accept_refuses_a_blank_and_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    before = _seq(lb)
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--accept", "1,3"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "proposal 3 has no name" in err and '--name 3 "' in err
    assert not (lb.root / "places.json").exists() and _seq(lb) == before, "every number checked first"
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--accept", "13"])
    assert e.value.code == 2 and "no proposal 13" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--accept", "1", "--reject", "1"])
    assert e.value.code == 2 and "both" in capsys.readouterr().err


def test_name_accepts_with_the_owner_s_own_name(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _review(capsys, "--name", "3", "Base", "--name", "1", "Cabin")
    assert "accepted 3 → Base" in out and "accepted 1 → Cabin" in out
    written = _places_json(lb)
    assert set(written) == {"Base", "Cabin"}
    assert places.distance_m(written["Base"]["lat"], written["Base"]["lon"], *S[3]) < 10
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--name", "1", "base"])
    assert e.value.code == 2 and "already a place" in capsys.readouterr().err


def test_reject_records_the_pair_beside_the_record_and_it_is_not_proposed_again(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _seq(lb)
    out = _review(capsys, "--reject", "4")
    assert f"rejected 4 ≠ {BOATHOUSE}" in out
    state = json.loads((lb.root / "state" / "places-review.json").read_text(encoding="utf-8"))
    [pair] = state["rejected"]
    assert pair["name"] == BOATHOUSE and places.distance_m(pair["lat"], pair["lon"], *S[4]) < 10
    assert _seq(lb) == before, "a note beside the record, never a line"
    data = _json(capsys)
    assert data["proposals"][3]["name"] is None, "its only name rejected: a blank now"
    assert any(e["name"] == BOATHOUSE for e in data["proposals"][3]["evidence"]), "the evidence stays"
    _review(capsys, "--reject", "4")
    data = _json(capsys)
    assert len(data["proposals"]) == 11 and data["held_back"] == 1, "a rejected blank: out of the queue"
    assert all(p["name"] != BOATHOUSE for p in data["proposals"])


def test_a_reviewed_place_renders_by_name_on_the_day_and_in_serve_at_once(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    site = serve.Site(lb)
    page = site.respond(f"/day/{DAYS[1]}", "").body.decode("utf-8")
    assert CABIN not in page and "55.6000,4.4000" in page
    before = json.loads(_day(capsys, DAYS[1]))
    assert before["nights"]["after"]["where"].startswith("55.6000,4.4000")
    _review(capsys, "--accept", "1")
    after = json.loads(_day(capsys, DAYS[1]))
    assert after["nights"]["after"]["where"] == CABIN
    assert after["nights"]["before"]["where"] == CABIN
    stays = [e for e in after["timeline"] if e["kind"] == "stay" and e["place"] == CABIN]
    assert stays and all(e["where"] == CABIN for e in stays)
    page = site.respond(f"/day/{DAYS[1]}", "").body.decode("utf-8")
    assert CABIN in page, "the running server reads places.json on the next request"


def _day(capsys: pytest.CaptureFixture[str], day: str) -> str:
    cli.main(["day", day, "--json"])
    return capsys.readouterr().out


def test_review_opens_no_connection_and_looks_nothing_up(
    lb: Logbook, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    _review(capsys)
    _json(capsys, "--near", "55.61,4.335", "--top", "2")
    _review(capsys, "--name", "3", "Base", "--reject", "4")
    assert no_network == []


def test_near_and_top_filter_the_list_and_keep_the_queue_s_numbers(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Four kilometres west of the grid only its first column is within 5 km: S1, S5 and S9."""
    data = _json(capsys, "--near", "55.61,4.335")
    assert [p["number"] for p in data["proposals"]] == [1, 5, 9]
    assert [p["number"] for p in _json(capsys, "--near", "55.61,4.335", "--top", "2")["proposals"]] == [1, 5]
    assert _json(capsys, "--top", "0")["proposals"] == [], "as `propose --top 0`: nothing listed"
    places.add(lb.root, places.Place("Rig", 55.61, 4.335, 100))
    assert [p["number"] for p in _json(capsys, "--near", "rig")["proposals"]] == [1, 5, 9]
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--near", "Atlantis"])
    assert e.value.code == 2 and "Atlantis" in capsys.readouterr().err


def test_a_named_place_is_observed_and_never_proposed(lb: Logbook) -> None:
    places.add(lb.root, places.Place("Base", *S[3], 150))
    report = places_review.read(lb)
    assert (len(report.observed), report.named, len(report.proposals)) == (12, 1, 11)
    assert 3 not in {_spot(p.lat, p.lon) for p in report.proposals}
    assert [o.place for o in report.observed if _spot(o.lat, o.lon) == 3] == ["Base"]


def test_a_place_taken_is_passed_over_for_the_next_name(lb: Logbook) -> None:
    """The owner already has a place called what the Timeline calls the cabin, elsewhere: the
    proposal falls back to the next name the record holds for the spot."""
    places.add(lb.root, places.Place(CABIN, 78.2, 15.6, 100))  # on Svalbard
    report = places_review.read(lb)
    assert report.proposals[0].name == "Home"


def test_interactive_y_n_or_a_name_on_a_tty(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_command, "_on_a_tty", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\nn\ny\n\nThe base\nq\n"))
    out = _review(capsys)
    assert f"accepted 1 → {CABIN}" in out and f"rejected 2 ≠ {WORKSHOP}" in out
    assert "no name to accept" in out, "y on a blank asks again"
    assert "accepted 4 → The base" in out
    assert set(_places_json(lb)) == {CABIN, "The base"}
    state = json.loads((lb.root / "state" / "places-review.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in state["rejected"]] == [WORKSHOP]


def test_interactive_stops_at_the_end_of_input_and_json_never_asks(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(places_command, "_on_a_tty", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    _review(capsys)
    assert not (lb.root / "places.json").exists()
    assert len(_json(capsys)["proposals"]) == 12


# -- the table, the radius, the other sources -------------------------------------------------------------


def test_the_table_is_served_while_the_record_stands_and_rebuilt_when_it_moves(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = []
    real = places_review.build

    def counting(*args: Any, **kwargs: Any) -> list[places_review.Observed]:
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(places_review, "build", counting)
    first = places_review.observed(lb)
    assert places_review.observed(lb) == first and len(built) == 1, "served from index.sqlite"
    places.add(lb.root, places.Place("Rig", 55.61, 4.335, 100))
    places_review.observed(lb)
    assert len(built) == 2, "places.json changed: rebuilt"
    lb.append(at="2026-02-20T10:00:00Z", source="manual", kind="note", tier=2,
              payload={"schema": "note/v1", "text": "a later note"})  # fmt: skip
    places_review.observed(Logbook(lb.root))
    assert len(built) == 3, "the head moved: rebuilt"
    with sqlite3.connect(lb.index_path) as db:  # the view of a table of another shape
        db.execute(f"DROP VIEW {places_review.TABLE}")
        db.execute("DROP VIEW observed_people")
        db.execute("ALTER TABLE observed_entities DROP COLUMN labels")
    places_review.observed(Logbook(lb.root))
    assert len(built) == 4, "a table of another shape: rebuilt"


def test_the_fitted_radius_holds_the_spread_and_stays_out_of_other_places() -> None:
    fit = places_review.fit_radius
    assert fit(0, 55.6, 4.4, []) == 75
    assert fit(42, 55.6, 4.4, []) == 120
    assert fit(400, 55.6, 4.4, []) == 300
    neighbour = places.Place("Rig", 55.6, 4.4 + 250 / 62_900, 150)  # 250 m east, 150 m round
    assert fit(42, 55.6, 4.4, [neighbour]) == 99, "drawn back to the neighbour's edge, whole metres"
    close = places.Place("Rig", 55.6, 4.4 + 180 / 62_900, 150)
    assert fit(42, 55.6, 4.4, [close]) == 50, "never below 50 m"


def test_dawarich_names_a_stay_from_the_place_its_geocoder_put_on_the_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import dwell

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    points = dwell("2026-02-02", "10:00", "13:00", (56.2, 3.1), every_min=10, noise_m=15)
    for p in points:
        p["payload"]["extra"] = {"place": {"name": "Bøye A", "city": "Nordsjøen", "countrycode": "XX"}}
    lb.append_many(points)
    [proposal] = places_review.read(lb).proposals
    assert proposal.name == "Bøye A"
    [said] = proposal.observed.names
    assert (said.source, said.origin, said.count, said.unit) == ("dawarich", "dawarich", 1, "stay")


def test_an_empty_record_has_nothing_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert "no places observed" in _review(capsys)
    assert _json(capsys)["proposals"] == []
