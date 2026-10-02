"""`places.json` and `logbook places list|add|name|propose`: the named places of the record, and the
unnamed stays the readers propose for naming. Synthetic Oslo persona; nothing but a naming is ever
appended, and that is one note/v1 line."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from persona import BOAT, CAFE, FJORD, HOME, PLACES, ZURICH, persona_drafts, persona_record

from logbook import cli, places
from logbook.store import Logbook


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["places", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


# -- the file ---------------------------------------------------------------------------------------------


def test_the_old_shape_still_reads_and_a_missing_kind_is_other(tmp_path: Path) -> None:
    (tmp_path / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.91, "lon": 10.75, "radius_m": 120}}), encoding="utf-8"
    )
    [home] = places.read(tmp_path, 150)
    assert (home.name, home.kind, home.tags) == ("Home", "other", ())
    assert places.home_places([home]) == []


def test_kind_and_tags_are_read_and_a_bad_kind_is_refused(tmp_path: Path) -> None:
    (tmp_path / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.91, "lon": 10.75, "kind": "home", "tags": ["family"]}}),
        encoding="utf-8",
    )
    [home] = places.read(tmp_path, 150)
    assert home.kind == "home" and home.tags == ("family",) and home.radius_m == 150
    assert places.home_places([home]) == [home]
    (tmp_path / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.91, "lon": 10.75, "kind": "castle"}}), encoding="utf-8"
    )
    with pytest.raises(places.PlaceError):
        places.read(tmp_path, 150)


def test_stay_ids_name_a_stay_by_its_start_and_centre() -> None:
    assert places.parse_stay_id("stay:owner:20260610T1000Z@59.9200,10.7400") == (59.92, 10.74)
    assert places.parse_stay_id("59.92,10.74") == (59.92, 10.74)
    assert places.parse_stay_id("59.92, 10.74") == (59.92, 10.74)
    with pytest.raises(ValueError):
        places.parse_stay_id("Home")
    with pytest.raises(ValueError):
        places.parse_stay_id("95,10")


# -- list and add -------------------------------------------------------------------------------------------


def test_list_says_so_when_there_are_no_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _empty(tmp_path, monkeypatch)
    assert "no places" in _run(capsys, "list")


def test_add_writes_the_entry_and_list_shows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _empty(tmp_path, monkeypatch)
    out = _run(
        capsys, "add", "Home", "--lat", "59.9139", "--lon", "10.7522", "--radius", "120", "--kind", "home"
    )
    assert "Home" in out
    out = _run(capsys, "add", "Cafe", "--lat", "59.92", "--lon", "10.74", "--tags", "coffee, work")
    written = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert written["Home"] == {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}
    assert written["Cafe"] == {
        "lat": 59.92,
        "lon": 10.74,
        "radius_m": 150,
        "kind": "other",
        "tags": ["coffee", "work"],
    }
    text = _run(capsys, "list")
    assert "Home" in text and "home" in text and "Cafe" in text and "coffee" in text
    assert lb.meta["seq"] == 0, "add edits the registry; it appends nothing"


def test_add_refuses_a_name_already_taken_and_coordinates_off_the_earth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _empty(tmp_path, monkeypatch)
    _run(capsys, "add", "Home", "--lat", "59.9", "--lon", "10.7")
    with pytest.raises(SystemExit) as e:
        cli.main(["places", "add", "home", "--lat", "59.9", "--lon", "10.7"])
    assert e.value.code == 2 and "Home" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["places", "add", "Pole", "--lat", "95", "--lon", "10.7"])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["places", "add", "Tiny", "--lat", "59.9", "--lon", "10.7", "--radius", "0"])


def test_an_unreadable_file_is_refused_with_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _empty(tmp_path, monkeypatch)
    (lb.root / "places.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["places", "list"])
    assert e.value.code == 2 and "places.json" in capsys.readouterr().err


# -- name -------------------------------------------------------------------------------------------------


def test_name_adds_the_place_and_puts_the_naming_in_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _empty(tmp_path, monkeypatch)
    out = _run(capsys, "name", "59.92,10.74", "Cafe", "--tags", "coffee")
    assert "Cafe" in out
    written = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert written["Cafe"]["lat"] == 59.92 and written["Cafe"]["tags"] == ["coffee"]
    [line] = lb.lines()
    assert (line["kind"], line["source"], line["tier"]) == ("note", "manual", 2)
    assert line["payload"] == {"schema": "note/v1", "text": "named 59.92,10.74 as Cafe"}
    assert lb.verify()[2] == []


def test_name_accepts_a_stay_id_from_propose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "propose", "--since", "2026-06-10", "--until", "2026-06-10")
    [cafe] = data["proposals"]
    stay_id = cafe["stays"][0]
    seq = lb.meta["seq"]
    _run(capsys, "name", stay_id, "Cafe", "--kind", "other")
    written = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert abs(written["Cafe"]["lat"] - CAFE[0]) < 0.001 and abs(written["Cafe"]["lon"] - CAFE[1]) < 0.001
    assert written["Home"]["kind"] == "home", "the other entries are kept"
    assert lb.meta["seq"] == seq + 1


# -- propose ----------------------------------------------------------------------------------------------


def test_propose_lists_unnamed_stays_ranked_by_hours_with_what_is_near(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21")
    assert data["window"]["days"][0] == "2026-06-08"
    proposals = data["proposals"]
    hours = [p["hours"] for p in proposals]
    assert hours == sorted(hours, reverse=True), "ranked by total hours"
    # The hotel in Zürich (three days), the anchorage (a day), the cafe (an hour), the airports.
    zurich, fjord = proposals[0], proposals[1]
    assert abs(zurich["lat"] - ZURICH[0]) < 0.002 and abs(zurich["lon"] - ZURICH[1]) < 0.002
    assert zurich["hours"] > 70
    assert zurich["nearest"] is None or zurich["nearest"]["metres"] > 100_000
    assert abs(fjord["lat"] - FJORD[0]) < 0.002
    assert fjord["nearest"]["name"] == "Marina" and 5_000 < fjord["nearest"]["metres"] < 15_000
    assert fjord["aboard"] == "solvind"
    cafe = next(p for p in proposals if abs(p["lat"] - CAFE[0]) < 0.001)
    assert cafe["nearest"]["name"] == "Home"
    assert cafe["timeline"][0]["semantic_type"] == "RESTAURANT"
    assert cafe["timeline"][0]["place_id"].startswith("ChIJ")
    assert cafe["suggested"] == "Restaurant"
    assert cafe["stays"][0].startswith("stay:owner:20260610T")
    assert cafe["lines"]["points"] > 5 and len(cafe["lines"]["first"]) == 36
    assert all(abs(p["lat"] - HOME[0]) > 0.001 for p in proposals), "named places are never proposed"
    assert lb.meta["head"] == head, "propose appends nothing"
    text = _run(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21")
    assert "Restaurant" in text and "Marina" in text and "aboard solvind" in text
    assert "stay:owner:" in text


def test_propose_write_names_what_the_captain_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    # The hotel is named, the anchorage is accepted as suggested, the rest are skipped by quitting.
    monkeypatch.setattr("sys.stdin", io.StringIO("Hotel Zürich\n\nq\n"))
    out = _run(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21", "--write")
    written = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert "Hotel Zürich" in written and abs(written["Hotel Zürich"]["lat"] - ZURICH[0]) < 0.002
    anchorage = next(name for name in written if name not in PLACES and name != "Hotel Zürich")
    assert abs(written[anchorage]["lat"] - FJORD[0]) < 0.002
    assert lb.meta["seq"] == seq + 2, "one note per naming"
    notes = [
        line for line in lb.lines() if line["kind"] == "note" and line["payload"]["text"].startswith("named ")
    ]
    assert len(notes) == 2 and notes[0]["payload"]["text"].endswith("as Hotel Zürich")
    assert "Hotel Zürich" in out
    # Named now, so no longer proposed.
    data = _json(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21")
    assert all(abs(p["lat"] - ZURICH[0]) > 0.002 for p in data["proposals"])


def test_propose_without_a_window_reads_the_whole_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "propose", "--top", "2")
    assert len(data["proposals"]) == 2
    assert data["window"]["days"][0] <= "2026-06-08" and data["window"]["days"][-1] >= "2026-06-21"


def _jsonl_opens(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every month file opened from here on: the record's lines are only ever read through `Path.open`."""
    opened: list[Path] = []
    original = Path.open

    def counting(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".jsonl":
            opened.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting)
    return opened


def test_propose_reads_the_index_and_not_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner's points, the boat's, the evidence that promotes a stay and the retractions all
    come from the index's own columns; with the index current, no month file is opened."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(d for d in persona_drafts() if d["source"] != "google-takeout")
    (lb.root / "assets.json").write_text(
        json.dumps({"assets": [{"id": BOAT, "kind": "yacht", "name": "Solvind", "mmsi": "999000001"}]}),
        encoding="utf-8",
    )
    (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2), encoding="utf-8")
    with lb.index():
        pass
    opened = _jsonl_opens(monkeypatch)
    data = _json(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21")
    assert opened == []
    proposals = data["proposals"]
    fjord = next(p for p in proposals if abs(p["lat"] - FJORD[0]) < 0.002)
    assert fjord["aboard"] == BOAT, "the boat's track is read too, so a stay aboard still says so"
    assert any(abs(p["lat"] - ZURICH[0]) < 0.002 for p in proposals)


def test_propose_opens_a_file_only_for_the_timeline_visits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Google Timeline visit's semantic type lives in its payload, which the index does not hold:
    those lines, found through the index, are the only ones read from the files."""
    lb = persona_record(tmp_path, monkeypatch)
    with lb.index():
        pass
    opened = _jsonl_opens(monkeypatch)
    data = _json(capsys, "propose", "--since", "2026-06-08", "--until", "2026-06-21")
    assert len(opened) == 1 and opened[0].parts[-3:] == ("logbook", "2026", "06.jsonl")
    cafe = next(p for p in data["proposals"] if abs(p["lat"] - CAFE[0]) < 0.001)
    assert cafe["timeline"][0]["semantic_type"] == "RESTAURANT"


def test_propose_leaves_out_a_retracted_point_without_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A retraction is a line; the id it supersedes is a column of the index, so a retracted point is
    left out of the clustering with no file read."""
    lb = _empty(tmp_path, monkeypatch)
    far = (59.5, 10.0)
    seqs = []
    for minute in range(0, 120, 5):
        line = lb.append(
            at=f"2026-06-10T{10 + minute // 60:02d}:{minute % 60:02d}:00Z",
            source="dawarich",
            kind="location",
            tier=1,
            payload={"schema": "location/v1", "lat": far[0], "lon": far[1], "raw_id": f"p:{minute}"},
        )
        seqs.append(int(line["seq"]))
    before = _json(capsys, "propose", "--since", "2026-06-10", "--until", "2026-06-10")
    assert len(before["proposals"]) == 1 and before["proposals"][0]["lines"]["points"] == 24
    for seq in seqs[:12]:
        lb.retract(seq, "a test")
    with lb.index():
        pass
    opened = _jsonl_opens(monkeypatch)
    after = _json(capsys, "propose", "--since", "2026-06-10", "--until", "2026-06-10")
    assert opened == []
    assert after["proposals"][0]["lines"]["points"] == 12
    assert after["proposals"][0]["stays"][0].startswith("stay:owner:20260610T1100Z")


# -- home regions in derive stays ------------------------------------------------------------------------


def test_the_night_knows_whether_it_was_at_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    cli.main(["derive", "stays", "--since", "2026-06-12", "--until", "2026-06-15", "--json"])
    data = json.loads(capsys.readouterr().out)
    nights = {n["day"]: n for n in data["nights"]}
    assert nights["2026-06-12"]["home"] is True and nights["2026-06-12"]["stay"]["place"] == "Home"
    assert nights["2026-06-13"]["home"] is False and nights["2026-06-13"]["stay"]["aboard"] == "solvind"
    assert nights["2026-06-15"]["home"] is False
    cli.main(["derive", "stays", "--since", "2026-06-12", "--until", "2026-06-13"])
    text = capsys.readouterr().out
    assert "night          Home" in text


def test_without_home_places_no_night_is_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch, places=None)
    cli.main(["derive", "stays", "--day", "2026-06-12", "--json"])
    data = json.loads(capsys.readouterr().out)
    [night] = data["nights"]
    assert night["home"] is False and night["in_transit"] is False


def test_home_is_the_place_kind_not_the_name() -> None:
    home = places.Place("Flat", 59.9139, 10.7522, 120, "home")
    office = places.Place("Home Office", 59.91, 10.76, 120, "other")
    assert places.at_home(59.9140, 10.7523, [home, office]) is home
    assert places.at_home(59.91, 10.76, [home, office]) is None
