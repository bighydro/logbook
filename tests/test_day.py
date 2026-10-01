"""`logbook day YYYY-MM-DD [--json]`: one calendar day read back from the record — the nights
either side, the country, the timeline of stays, moves, stops and flights with what attached to
each and who was there, the health line, and which sources spoke. Synthetic Oslo persona, who
does not exist; nothing is written, and the day is located through the index, never a scan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import (
    BOAT,
    HOME,
    KARI,
    KARI_ID,
    OLA_ID,
    PLACES,
    TZ,
    attendee,
    dwell,
    event,
    persona_record,
    resolution,
    travel,
    utc,
)

from logbook import cli
from logbook import day as day_reader
from logbook.index import Index
from logbook.store import Logbook

EN_DASH = "\u2013"
FAR = (59.9600, 10.8200)  # ~5 km from HOME: too far for a silence to be read as stillness


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["day", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# -- a normal day at home ---------------------------------------------------------------------------------


def test_an_office_day_at_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head, before = lb.meta["head"], _files(lb.root)
    data = _json(capsys, "2026-06-09")
    assert data["day"] == "2026-06-09" and data["weekday"] == "Tuesday" and data["tz"] == TZ
    nights = data["nights"]
    assert nights["before"]["day"] == "2026-06-08" and nights["before"]["where"] == "Home"
    assert nights["before"]["home"] is True and nights["before"]["in_transit"] is False
    assert nights["after"]["day"] == "2026-06-09" and nights["after"]["where"] == "Home"
    assert nights["after"]["home"] is True
    assert data["country"] == {"code": "NO", "method": "airport", "by": "OSL", "from": "night"}
    kinds = [(e["kind"], e["where"]) for e in data["timeline"]]
    assert kinds == [
        ("stay", "Home"),
        ("move", None),
        ("stay", "Office"),
        ("move", None),
        ("stay", "Home"),
    ]
    first, _walk, office, _back, last = data["timeline"]
    assert first["within_day"]["start"] == "2026-06-08T22:00:00Z", "the stay began the evening before"
    assert first["start"] < first["within_day"]["start"], "the entry keeps its real start"
    assert last["within_day"]["end"] == "2026-06-09T22:00:00Z", "and runs past midnight"
    assert office["attached"]["events"] == [] and office["with"] == {"confirmed": [], "proposed": []}
    assert office["lines"]["first"] and office["lines"]["last"], "a stay points at its location lines"
    assert data["flights"] == [] and data["all_day"] == [] and data["unplaced"] == []
    assert data["health"] is None
    [dawarich] = data["sources"]
    assert dawarich["source"] == "dawarich" and dawarich["lines"] > 100
    assert dawarich["newest"].startswith("2026-06-09T21:5"), "the tracker's last word of the day"
    assert lb.meta["head"] == head and _files(lb.root) == before, "a Day writes nothing, not even settings"
    text = _run(capsys, "2026-06-09")
    assert text.splitlines()[0] == "2026-06-09  Tuesday"
    assert "night before  Home · home" in text and "night after   Home · home" in text
    assert "country       NO" in text
    assert f"00:00{EN_DASH}07:30" in text or f"00:00{EN_DASH}08:00" in text
    assert "stay   Office" in text and "walk" in text
    assert "health        no lines" in text
    assert "sources       dawarich" in text


# -- a travel day with a flight -------------------------------------------------------------------------


def test_a_travel_day_has_its_flight_and_sleeps_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "2026-06-15")
    assert data["nights"]["before"]["where"] == "Home" and data["nights"]["before"]["home"] is True
    after = data["nights"]["after"]
    assert after["home"] is False and after["in_transit"] is False and after["where"].startswith("47.37")
    assert after["where"].endswith(" (Zurich)"), "9 km from the airport, no named place: the airport's city"
    assert data["country"]["code"] == "CH" and data["country"]["from"] == "night"
    [flight] = data["flights"]
    assert (flight["carrier"], flight["number"], flight["from"], flight["to"]) == ("XY", "561", "OSL", "ZRH")
    assert flight["evidence"] == "tracked" and flight["role"] == "passenger" and flight["line"]
    assert flight["start"] == utc("2026-06-15", "07:05") and flight["end"] == utc("2026-06-15", "09:15")
    moves = [e for e in data["timeline"] if e["kind"] == "move"]
    [hop] = [m for m in moves if m["mode"] == "flight"]
    assert hop["airports"] == ["OSL", "ZRH"]
    assert hop["flights"] == [flight["id"]], "the move names the flight line that covers it"
    flights_in_timeline = [e for e in data["timeline"] if e["kind"] == "flight"]
    assert [f["id"] for f in flights_in_timeline] == [flight["id"]], "and the flight is a row of the timeline"
    text = _run(capsys, "2026-06-15")
    assert "flight XY 561  OSL → ZRH · tracked" in text
    assert "night after   47.37" in text and "(Zurich) · away" in text
    hotel = data["timeline"][-1]
    assert hotel["kind"] == "stay" and hotel["place"] is None
    assert hotel["where"] == f"{hotel['lat']:.4f},{hotel['lon']:.4f} (Zurich)", "the stay's row says so too"
    assert "country       CH" in text


# -- a day aboard an asset --------------------------------------------------------------------------------


def test_a_day_aboard_the_boat_is_one_stay_with_the_anchorages_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    cli.main(["infer", "keepers"])
    capsys.readouterr()
    data = _json(capsys, "2026-06-13")
    kinds = [e["kind"] for e in data["timeline"]]
    assert kinds == ["stay", "move", "aboard"], "the boat's own movement does not fragment the stay aboard"
    aboard = data["timeline"][2]
    assert aboard["asset"] == {"id": BOAT, "name": "Solvind", "kind": "yacht"}
    assert aboard["where"] == "aboard Solvind"
    assert aboard["within_day"]["end"] == "2026-06-13T22:00:00Z", "clipped to the day; the night is aboard"
    assert [(s["kind"], (s["where"] or "")[:5], s["mode"]) for s in aboard["inside"]] == [
        ("stay", "Marin", None),
        ("move", "", "boat"),
        ("stay", "59.85", None),
    ]
    attached = aboard["attached"]
    assert [n["text"] for n in attached["notes"]] == ["Anchored in the bay with Ola Nordmann. Grilled."]
    assert attached["photos"]["count"] == 1 and len(attached["photos"]["lines"]) == 1
    assert [k["lane"] for k in attached["keepers"]] == ["memory"]
    [ola] = aboard["with"]["confirmed"]
    assert ola["person"] == OLA_ID and ola["name"] == "Ola Nordmann" and ola["sources"] == ["note"]
    assert aboard["with"]["proposed"] == []
    after = data["nights"]["after"]
    assert after["aboard"] == BOAT and after["home"] is False and after["where"] == "aboard Solvind"
    text = _run(capsys, "2026-06-13")
    assert "aboard Solvind" in text and "night after   aboard Solvind · away" in text
    assert "with         Ola Nordmann (note)" in text
    assert "keeper       IMG_131730.HEIC (memory)" in text


# -- with, from a note ------------------------------------------------------------------------------------


def test_a_note_names_company_only_when_the_record_resolves_the_name_to_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`with US and XYZ` names no one: a capitalised word is company only when a resolution line
    makes it a person, the rule transcripts already follow."""
    from persona import note

    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [note(utc("2026-06-09", "10:00"), "Standup with US and XYZ about Norway, then coffee with Ola")]
    )
    data = _json(capsys, "2026-06-09")
    [office] = [e for e in data["timeline"] if e["where"] == "Office"]
    assert [n["text"] for n in office["attached"]["notes"]] == [
        "Standup with US and XYZ about Norway, then coffee with Ola"
    ]
    assert [c["name"] for c in office["with"]["confirmed"]] == ["Ola Nordmann"]
    assert office["with"]["proposed"] == []
    text = _run(capsys, "2026-06-09")
    assert "with         Ola Nordmann (note)" in text
    assert "US" not in text.split("with         ")[1].splitlines()[0]


# -- a day with a tracker gap, and the health line -------------------------------------------------------


def _health(
    at: str, type_: str, value: float, device: str, end: str | None = None, **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "health-sample/v1",
        "raw_id": f"{type_}:{at}:{device}",
        "type": type_,
        "value": value,
        "unit": {"steps": "count", "sleep": "s", "resting_hr": "count/min"}[type_],
        "device": device,
        **extra,
    }
    return {"at": at, "end": end, "source": "apple-health", "kind": "health", "tier": 3, "payload": payload}


def _gap_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Thursday 2 July 2026: home until 09:00, then the tracker is silent until 17:00, when the
    owner is already 5 km away; back home for the night. A lunch is in the calendar during the
    silence. The night's sleep, the day's steps and two resting readings, the second correcting
    the first, are health lines."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    day, before, after = "2026-07-02", "2026-07-01", "2026-07-03"
    drafts: list[dict[str, Any]] = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        *dwell(before, "19:00", "24:00", HOME, every_min=5),
        *dwell(day, "00:00", "09:00", HOME, every_min=5),
        *dwell(day, "17:00", "19:00", FAR, every_min=5),
        *travel(day, "19:00", "19:30", FAR, HOME, steps=4),
        *dwell(day, "19:30", "24:00", HOME, every_min=5),
        *dwell(after, "00:00", "08:00", HOME, every_min=5),
        event(utc(day, "12:00"), utc(day, "13:00"), "Lunch", [attendee(KARI["email"], "Kari Nordmann")]),
        event(
            utc(day, "00:00"),
            utc(after, "00:00"),
            "Kari in town",
            [attendee(KARI["email"])],
            all_day=True,
            location="Home",  # located at the stay through places.json: proposed there, nowhere else
        ),
        _health(utc(before, "23:00"), "sleep", 3 * 3600, "Watch7,1", end=utc(day, "02:00"), stage="core"),
        _health(utc(day, "02:00"), "sleep", 4 * 3600, "Watch7,1", end=utc(day, "06:00"), stage="deep"),
        _health(utc(before, "22:30"), "sleep", 8 * 3600, "Watch7,1", end=utc(day, "06:30"), stage="in_bed"),
        _health("2026-07-02T06:00:00Z", "steps", 250, "Watch7,1", end="2026-07-02T06:15:00Z"),
        _health("2026-07-02T06:00:00Z", "steps", 200, "iPhone17,1", end="2026-07-02T06:15:00Z"),
        _health("2026-07-02T15:00:00Z", "steps", 3000, "Watch7,1", end="2026-07-02T15:15:00Z"),
        _health("2026-07-02T05:00:00Z", "resting_hr", 3360, "Watch7,1"),
    ]
    lb.append_many(drafts)
    with lb.index() as idx:
        [wrong] = [line for line in idx.day(day) if (line["payload"].get("type")) == "resting_hr"]
    corrected = _health("2026-07-02T05:00:00Z", "resting_hr", 56, "Watch7,1", supersedes=str(wrong["id"]))
    corrected["payload"]["raw_id"] += ":u2"
    lb.append_many([corrected])
    (lb.root / "places.json").write_text(json.dumps({"Home": PLACES["Home"]}), encoding="utf-8")
    return lb


def test_a_tracker_gap_is_a_row_the_lunch_is_unplaced_and_health_takes_the_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _gap_record(tmp_path, monkeypatch)
    data = _json(capsys, "2026-07-02")
    kinds = [(e["kind"], (e["where"] or "")[:5], e["gap"]) for e in data["timeline"]]
    assert kinds == [
        ("stay", "Home", False),
        ("move", "", True),
        ("stay", "59.96", False),
        ("move", "", False),
        ("stay", "Home", False),
    ]
    gap = data["timeline"][1]
    assert gap["points"] == 0 and gap["start"] == utc("2026-07-02", "09:00")
    assert gap["end"] == utc("2026-07-02", "17:00"), "a move the tracker did not see is a gap, said so"
    [lunch] = data["unplaced"]
    assert lunch["kind"] == "event" and lunch["title"] == "Lunch" and lunch["line"]
    assert [a["title"] for a in data["all_day"]] == ["Kari in town"]
    for entry in data["timeline"]:
        assert entry["with"]["confirmed"] == [], "an all-day event confirms nobody"
    proposed = {p["name"] for e in data["timeline"] if e["kind"] == "stay" for p in e["with"]["proposed"]}
    assert proposed == {"Kari Nordmann"}, "it proposes its attendees"
    health = data["health"]
    assert health["sleep_h"] == 7.0 and health["steps"] == 3250 and health["resting_hr"] == 56
    assert len(health["lines"]) == 5, "the asleep stages, the three buckets' winners and the reading standing"
    sources = {s["source"]: s for s in data["sources"]}
    assert set(sources) == {"dawarich", "ios-calendar", "apple-health"}
    assert sources["dawarich"]["newest"].startswith("2026-07-02T21:5")
    text = _run(capsys, "2026-07-02")
    assert f"09:00{EN_DASH}17:00  gap    8 h · no points" in text
    assert "unplaced" in text and "Lunch" in text
    assert "all day       Kari in town" in text
    assert "health        sleep 7.0 h · 3,250 steps · resting 56 bpm" in text


# -- the edges ---------------------------------------------------------------------------------------------


def test_a_day_with_no_lines_and_a_bad_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "2026-07-20")
    assert data["timeline"] == [] and data["sources"] == []
    assert data["nights"]["after"]["in_transit"] is True and data["nights"]["after"]["where"] is None
    assert data["country"] == {"code": None, "method": None, "by": None, "from": None}
    text = _run(capsys, "2026-07-20")
    assert "nothing logged" in text and "in transit" in text
    with pytest.raises(SystemExit) as e:
        cli.main(["day", "2026-13-01"])
    assert e.value.code == 2 and "not a date" in capsys.readouterr().err


def test_the_day_is_read_through_the_index_never_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    with lb.index():
        pass  # built once, here, so the reading below cannot be the rebuild

    def scan(*_: Any, **__: Any) -> Any:
        raise AssertionError("a Day never sweeps the files")

    monkeypatch.setattr(Logbook, "lines", scan)
    monkeypatch.setattr(Logbook, "lines_unsorted", scan)
    monkeypatch.setattr(Logbook, "located_lines", scan)
    monkeypatch.setattr(Index, "of_kind", scan)
    data = day_reader.read(lb, "2026-06-10")
    assert data["day"] == "2026-06-10"
    [cafe] = [e for e in data["timeline"] if e["where"] == "59.9200,10.7400"]
    assert [c["name"] for c in cafe["with"]["confirmed"]] == ["Kari Nordmann"]
    proposed = [c["name"] for c in cafe["with"]["proposed"]]
    assert proposed == [], "the face is the same person, already confirmed"
    assert [e["title"] for e in cafe["attached"]["events"]] == ["Lunch"]
