"""`logbook places import-takeout`: Google Maps saved and starred places proposed for places.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib.adapters.takeout import places
from logbook.core.stays import read_places

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout"
SAVED_JSON = FIX / "Maps (your places)" / "Saved Places.json"
SAVED_CSV = FIX / "Saved"
TZ = "Europe/Oslo"


def test_the_geojson_export_proposes_a_place_per_feature_with_coordinates():
    found = places.read(SAVED_JSON)
    assert [p.name for p in found] == ["Havnekontoret", "59°51'00.0\"N 10°39'00.0\"E", "Nowhere"]
    first = found[0]
    assert (first.lat, first.lon, first.category) == (59.9075, 10.7389, "Saved Places")
    assert first.address == "Storgata 1, 0155 Oslo, Norway"
    assert found[2].lat is None and found[2].lon is None  # (0, 0) is no place


def test_a_saved_list_csv_proposes_a_place_per_row_with_coordinates_from_the_url_when_it_has_them():
    found = places.read(SAVED_CSV / "Want to go.csv")
    assert [p.name for p in found] == ["Havnekontoret", "Bygdøy sjøbad", "Slipway (unknown)"]
    assert found[0].lat is None  # a place id in the url, no coordinates
    assert (found[1].lat, found[1].lon, found[1].category) == (59.9052, 10.6792, "Want to go")
    assert found[1].note == "bring the kayak"
    (starred,) = places.read(SAVED_CSV / "Starred places.csv")
    assert (starred.lat, starred.lon, starred.category) == (59.9139, 10.7522, "Starred places")


def test_a_folder_reads_every_export_in_it_and_a_takeout_root_both_folders():
    assert len(places.read(SAVED_CSV)) == 4
    names = [p.name for p in places.read(FIX)]
    assert names.count("Havnekontoret") == 2 and "Oslofjord chart shop" in names


def test_other_files_are_not_places(tmp_path):
    assert places.read(FIX / "Keep") == []
    (tmp_path / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert places.read(tmp_path / "x.csv") == []
    with pytest.raises(FileNotFoundError):
        places.read(tmp_path / "missing.csv")


def test_merge_keeps_the_existing_file_adds_new_names_and_reports_the_rest(tmp_path):
    root = tmp_path / "lb"
    root.mkdir()
    (root / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.91, "lon": 10.75, "radius_m": 120, "note": "kept"}}), encoding="utf-8"
    )
    report = places.merge(root, places.read(FIX), write=False)
    assert [p.name for p in report.new] == [
        "Havnekontoret",
        "59°51'00.0\"N 10°39'00.0\"E",
        "Oslofjord chart shop",
        "Bygdøy sjøbad",
    ]
    assert [p.name for p in report.without_coordinates] == ["Nowhere", "Havnekontoret", "Slipway (unknown)"]
    assert report.existing == [] and report.written is False
    assert json.loads((root / "places.json").read_text(encoding="utf-8"))["Home"]["note"] == "kept"
    report = places.merge(root, places.read(FIX), write=True)
    assert report.written is True
    data = json.loads((root / "places.json").read_text(encoding="utf-8"))
    assert data["Home"] == {"lat": 59.91, "lon": 10.75, "radius_m": 120, "note": "kept"}
    assert data["Havnekontoret"] == {
        "lat": 59.9075,
        "lon": 10.7389,
        "category": "Saved Places",
        "address": "Storgata 1, 0155 Oslo, Norway",
    }
    assert data["Bygdøy sjøbad"] == {
        "lat": 59.9052,
        "lon": 10.6792,
        "category": "Want to go",
        "note": "bring the kayak",
    }
    assert [p.name for p in read_places(root, 100.0)] == list(data)  # stays reads it back
    again = places.merge(root, places.read(FIX), write=True)
    assert again.new == [] and [p.name for p in again.existing] == [p.name for p in report.new]


def test_cli_proposes_without_write_and_writes_with_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["places", "import-takeout", str(FIX)])
    out = capsys.readouterr().out
    assert "Havnekontoret" in out and "59.9075, 10.7389" in out and "Saved Places" in out
    assert "4 places proposed" in out and "3 without coordinates" in out and "nothing written" in out
    assert not (tmp_path / "lb" / "places.json").exists()
    cli.main(["places", "import-takeout", str(FIX), "--write"])
    out = capsys.readouterr().out
    assert "wrote 4 places to" in out
    data = json.loads((tmp_path / "lb" / "places.json").read_text(encoding="utf-8"))
    assert len(data) == 4
    cli.main(["places", "import-takeout", str(SAVED_CSV / "Starred places.csv"), "--write"])
    out = capsys.readouterr().out
    assert "1 already in places.json" in out and "wrote 0" not in out and "nothing new" in out


def test_cli_missing_path_exits_2(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    with pytest.raises(SystemExit) as e:
        cli.main(["places", "import-takeout", str(tmp_path / "nope.csv")])
    assert e.value.code == 2
    assert "places:" in capsys.readouterr().err
